"""
AI 기반 한국 주식 자동매매 시스템
- 키움증권 OpenAPI+ (Windows 32비트 Python 전용)
- GPT-4o + Gemini 1.5 Pro AI 분석
- 인기 종목 상위 20개 대상 30분 주기 자동매매
"""
import asyncio
import logging
import signal
import sys

import qasync
from PyQt5.QtWidgets import QApplication

from config.settings import load_config
from src.ai.decision_maker import DecisionMaker
from src.ai.gemini_analyzer import GeminiAnalyzer
from src.ai.gpt_analyzer import GPTAnalyzer
from src.kiwoom.api import KiwoomAPI
from src.scheduler.trading_scheduler import TradingScheduler
from src.trading.market_data import MarketDataFetcher
from src.trading.order_manager import OrderManager
from src.trading.portfolio_manager import PortfolioManager
from src.trading.risk_manager import RiskManager
from src.trading.stock_selector import StockSelector
from src.utils.logger import setup_logging


def main():
    app = QApplication(sys.argv)
    config = load_config("config/config.yaml")
    setup_logging(config.log_level, config.log_dir)
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("AI 주식 자동매매 시스템 시작")
    logger.info(f"모의투자: {config.kiwoom.is_simulated}")
    logger.info(f"대상 종목 수: {config.top_n_stocks}개")
    logger.info("=" * 60)

    # qasync로 Qt 이벤트 루프와 asyncio 루프 통합
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    # 의존성 주입
    kiwoom    = KiwoomAPI(config.kiwoom)
    portfolio = PortfolioManager(
        kiwoom,
        config.kiwoom.account_number,
        config.kiwoom.account_password,
        config.data_dir,
    )
    risk      = RiskManager(config.risk)
    order_mgr = OrderManager(
        kiwoom,
        portfolio,
        risk,
        config.kiwoom.account_number,
        config.kiwoom.account_password,
    )
    selector  = StockSelector(kiwoom)
    data      = MarketDataFetcher(kiwoom)
    gpt       = GPTAnalyzer(config.openai)
    gemini    = GeminiAnalyzer(config.gemini)
    decider   = DecisionMaker()

    scheduler = TradingScheduler(
        kiwoom=kiwoom,
        stock_selector=selector,
        market_data=data,
        gpt_analyzer=gpt,
        gemini_analyzer=gemini,
        decision_maker=decider,
        order_manager=order_mgr,
        portfolio_manager=portfolio,
        risk_manager=risk,
        config=config,
    )

    def graceful_shutdown(signum, frame):
        logger.info("종료 신호 수신 — 청산 후 종료합니다")
        scheduler.stop()
        try:
            order_mgr.close_all_positions()
            kiwoom.logout()
        except Exception as e:
            logger.error(f"종료 중 오류: {e}")
        portfolio.save_state()
        app.quit()

    signal.signal(signal.SIGINT,  graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    # 키움 로그인
    if not kiwoom.login():
        logger.critical("키움 로그인 실패 — 프로그램을 종료합니다")
        sys.exit(1)

    scheduler.start()
    logger.info("스케줄러 시작 완료. Qt 이벤트 루프 진입.")

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
