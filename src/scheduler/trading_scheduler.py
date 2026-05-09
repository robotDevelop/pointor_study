import asyncio
import logging

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import AppConfig
from src.ai.decision_maker import DecisionMaker
from src.ai.gemini_analyzer import GeminiAnalyzer
from src.ai.gpt_analyzer import GPTAnalyzer
from src.kiwoom.api import KiwoomAPI
from src.trading.market_data import MarketDataFetcher
from src.trading.order_manager import OrderManager
from src.trading.portfolio_manager import PortfolioManager
from src.trading.risk_manager import RiskManager
from src.trading.stock_selector import StockSelector
from src.utils.time_utils import is_market_open, now_kst

logger = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")


class TradingScheduler:
    """
    일과 스케줄 (KST):
      08:50 — 사전 준비 (포트폴리오 동기화, AI 헬스체크, 인기 종목 조회)
      09:05~15:00 — 30분마다 분석 사이클
      14:50 — 신규 매수 중단
      15:00 — 전 포지션 강제 청산
      15:35 — 일일 리포트 출력
    """

    def __init__(
        self,
        kiwoom: KiwoomAPI,
        stock_selector: StockSelector,
        market_data: MarketDataFetcher,
        gpt_analyzer: GPTAnalyzer,
        gemini_analyzer: GeminiAnalyzer,
        decision_maker: DecisionMaker,
        order_manager: OrderManager,
        portfolio_manager: PortfolioManager,
        risk_manager: RiskManager,
        config: AppConfig,
    ):
        self.kiwoom = kiwoom
        self.stock_selector = stock_selector
        self.market_data = market_data
        self.gpt_analyzer = gpt_analyzer
        self.gemini_analyzer = gemini_analyzer
        self.decision_maker = decision_maker
        self.order_manager = order_manager
        self.portfolio = portfolio_manager
        self.risk = risk_manager
        self.config = config
        self._target_stocks = []
        self.scheduler = AsyncIOScheduler(timezone=KST)
        self._setup_jobs()

    def _setup_jobs(self) -> None:
        self.scheduler.add_job(
            self.pre_market_setup,
            CronTrigger(hour=8, minute=50, day_of_week="mon-fri", timezone=KST),
            id="pre_market",
        )
        self.scheduler.add_job(
            self.analysis_cycle,
            CronTrigger(
                hour="9-14", minute="5,35",
                day_of_week="mon-fri", timezone=KST,
            ),
            id="analysis_cycle",
        )
        self.scheduler.add_job(
            self.pre_close_stop_buys,
            CronTrigger(hour=14, minute=50, day_of_week="mon-fri", timezone=KST),
            id="pre_close_stop_buys",
        )
        self.scheduler.add_job(
            self.close_all_positions,
            CronTrigger(hour=15, minute=0, day_of_week="mon-fri", timezone=KST),
            id="close_positions",
        )
        self.scheduler.add_job(
            self.end_of_day_report,
            CronTrigger(hour=15, minute=35, day_of_week="mon-fri", timezone=KST),
            id="eod_report",
        )

    async def pre_market_setup(self) -> None:
        logger.info("=== 사전 준비 시작 ===")
        self.risk.reset_daily_counters()
        await self.portfolio.sync_from_kiwoom()
        self.portfolio.load_state()
        self.order_manager.resume_new_buys()

        gpt_ok, gemini_ok = await asyncio.gather(
            self.gpt_analyzer.health_check(),
            self.gemini_analyzer.health_check(),
        )
        logger.info(f"AI 헬스체크: GPT={'OK' if gpt_ok else 'FAIL'}, Gemini={'OK' if gemini_ok else 'FAIL'}")

        self._target_stocks = await self.stock_selector.get_top_stocks(self.config.top_n_stocks)
        logger.info(f"오늘의 분석 대상: {[s['name'] for s in self._target_stocks]}")

    async def analysis_cycle(self) -> None:
        if not is_market_open():
            logger.debug("장 외 시간 — 분석 사이클 건너뜀")
            return

        now = now_kst().strftime("%H:%M")
        logger.info(f"=== 분석 사이클 시작 @ {now} KST ({len(self._target_stocks)}개 종목) ===")

        # 손절/익절 먼저 확인
        await self._check_stop_take_profits()

        # 종목별 AI 분석 및 주문
        for stock in self._target_stocks:
            code, name = stock["code"], stock["name"]
            try:
                stock_data = await self.market_data.fetch_stock_data(code, name)

                gpt_result, gemini_result = await asyncio.gather(
                    self._safe_analyze(self.gpt_analyzer, stock_data),
                    self._safe_analyze(self.gemini_analyzer, stock_data),
                )

                decision = self.decision_maker.make_decision(
                    gpt_result,
                    gemini_result,
                    min_confidence=self.config.risk.min_confidence,
                )

                gpt_info    = f"{gpt_result.action.value}({gpt_result.confidence:.2f})"    if gpt_result    else "ERR"
                gemini_info = f"{gemini_result.action.value}({gemini_result.confidence:.2f})" if gemini_result else "ERR"
                logger.info(
                    f"[{name}] GPT={gpt_info} Gemini={gemini_info} "
                    f"→ {decision.final_action.value}({decision.combined_confidence:.2f})"
                )

                await self.order_manager.execute_decision(decision)

            except Exception as e:
                logger.error(f"분석 실패 [{name}({code})]: {e}", exc_info=True)

        await self.portfolio.sync_from_kiwoom()
        self.portfolio.save_state()

    async def _safe_analyze(self, analyzer, stock_data):
        try:
            return await analyzer.analyze(stock_data)
        except Exception as e:
            logger.warning(f"{analyzer.__class__.__name__} 분석 실패 [{stock_data.name}]: {e}")
            return None

    async def _check_stop_take_profits(self) -> None:
        for code, position in list(self.portfolio._positions.items()):
            if self.risk.check_stop_loss(position.avg_buy_price, position.current_price):
                logger.warning(f"손절 트리거: {position.name} ({position.unrealized_pnl_pct:.1%})")
                await self.order_manager.sell_by_stop_loss(code)
            elif self.risk.check_take_profit(position.avg_buy_price, position.current_price):
                logger.info(f"익절 트리거: {position.name} ({position.unrealized_pnl_pct:.1%})")
                await self.order_manager.sell_by_stop_loss(code)

    async def pre_close_stop_buys(self) -> None:
        logger.info("=== 장 마감 30분 전: 신규 매수 중단 ===")
        self.order_manager.stop_new_buys()

    async def close_all_positions(self) -> None:
        logger.info("=== 장 마감: 전체 포지션 청산 ===")
        await self.order_manager.close_all_positions()

    async def end_of_day_report(self) -> None:
        await self.portfolio.sync_from_kiwoom()
        total    = self.portfolio._total_value
        cash     = self.portfolio._cash
        positions = len(self.portfolio._positions)
        history  = self.portfolio._trade_history
        today_str_prefix = now_kst().strftime("%Y-%m-%d")
        today_trades = [t for t in history if t.timestamp.startswith(today_str_prefix)]
        total_pnl = sum(t.pnl for t in today_trades if t.action == "SELL")

        logger.info(
            f"=== 일일 결산 ===\n"
            f"  평가금액: {total:,}원 | 예수금: {cash:,}원\n"
            f"  보유종목: {positions}개\n"
            f"  오늘 매매: {len(today_trades)}회 | 실현손익: {total_pnl:+,.0f}원"
        )
        self.portfolio.save_state()

    def start(self) -> None:
        self.scheduler.start()
        logger.info("트레이딩 스케줄러 시작")

    def stop(self) -> None:
        self.scheduler.shutdown(wait=False)
        logger.info("트레이딩 스케줄러 중지")
