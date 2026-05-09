import logging
from datetime import datetime

from src.ai.base_analyzer import Action
from src.ai.decision_maker import TradingDecision
from src.kiwoom.api import KiwoomAPI
from src.kiwoom.constants import OrderType, PriceType
from src.trading.portfolio_manager import PortfolioManager, TradeRecord
from src.trading.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class OrderManager:
    def __init__(
        self,
        kiwoom: KiwoomAPI,
        portfolio: PortfolioManager,
        risk: RiskManager,
        account_no: str,
        account_pw: str,
    ):
        self.kiwoom = kiwoom
        self.portfolio = portfolio
        self.risk = risk
        self.account_no = account_no
        self.account_pw = account_pw
        self._allow_new_buys = True

    def stop_new_buys(self) -> None:
        self._allow_new_buys = False
        logger.info("신규 매수 중단")

    def resume_new_buys(self) -> None:
        self._allow_new_buys = True

    async def execute_decision(self, decision: TradingDecision) -> bool:
        if decision.final_action == Action.BUY:
            return await self._execute_buy(decision)
        elif decision.final_action == Action.SELL:
            return await self._execute_sell(decision)
        return True  # HOLD: 아무 행동 없음

    async def _execute_buy(self, decision: TradingDecision) -> bool:
        risk_result = self.risk.check_buy(
            stock_code=decision.stock_code,
            current_price=decision.target_price or 1,
            portfolio_value=self.portfolio._total_value,
            available_cash=self.portfolio._cash,
            current_positions=self.portfolio.get_positions_value(),
            ai_confidence=decision.combined_confidence,
            allow_new_buys=self._allow_new_buys,
        )

        if not risk_result.approved:
            logger.info(f"매수 거부 [{decision.stock_name}]: {risk_result.reason}")
            return False

        try:
            await self.kiwoom.place_order(
                order_type=OrderType.BUY,
                stock_code=decision.stock_code,
                quantity=risk_result.adjusted_quantity,
                price=0,
                account_no=self.account_no,
                price_type=PriceType.MARKET,
            )
            self.risk.increment_trade_count()
            self.portfolio.record_trade(TradeRecord(
                code=decision.stock_code,
                name=decision.stock_name,
                action="BUY",
                quantity=risk_result.adjusted_quantity,
                price=0,
                timestamp=datetime.now().isoformat(),
                ai_action=decision.final_action.value,
                ai_confidence=decision.combined_confidence,
            ))
            logger.info(
                f"매수 주문: {decision.stock_name}({decision.stock_code}) "
                f"x{risk_result.adjusted_quantity} @ 시장가 (신뢰도={decision.combined_confidence:.2f})"
            )
            return True
        except Exception as e:
            logger.error(f"매수 주문 실패 [{decision.stock_name}]: {e}")
            return False

    async def _execute_sell(self, decision: TradingDecision, forced: bool = False) -> bool:
        position = self.portfolio.get_position(decision.stock_code)
        if not position:
            return False

        risk_result = self.risk.check_sell(
            stock_code=decision.stock_code,
            avg_buy_price=position.avg_buy_price,
            current_price=position.current_price,
            holding_quantity=position.quantity,
            forced=forced,
        )

        if not risk_result.approved:
            logger.info(f"매도 거부 [{decision.stock_name}]: {risk_result.reason}")
            return False

        try:
            await self.kiwoom.place_order(
                order_type=OrderType.SELL,
                stock_code=decision.stock_code,
                quantity=position.quantity,
                price=0,
                account_no=self.account_no,
                price_type=PriceType.MARKET,
            )
            self.risk.increment_trade_count()
            pnl = (position.current_price - position.avg_buy_price) * position.quantity
            self.portfolio.record_trade(TradeRecord(
                code=decision.stock_code,
                name=decision.stock_name,
                action="SELL",
                quantity=position.quantity,
                price=position.current_price,
                timestamp=datetime.now().isoformat(),
                ai_action=decision.final_action.value,
                ai_confidence=decision.combined_confidence,
                pnl=float(pnl),
            ))
            logger.info(
                f"매도 주문: {decision.stock_name}({decision.stock_code}) "
                f"x{position.quantity} @ 시장가 PnL={pnl:+,}원"
            )
            return True
        except Exception as e:
            logger.error(f"매도 주문 실패 [{decision.stock_name}]: {e}")
            return False

    async def sell_by_stop_loss(self, stock_code: str) -> bool:
        position = self.portfolio.get_position(stock_code)
        if not position:
            return False
        decision = TradingDecision(
            stock_code=stock_code,
            stock_name=position.name,
            final_action=Action.SELL,
            combined_confidence=1.0,
            gpt_result=None,
            gemini_result=None,
            consensus=False,
            target_price=position.current_price,
            stop_loss_price=position.current_price,
            reasoning_summary="손절/익절 트리거",
        )
        logger.warning(f"손절/익절 실행: {position.name} ({position.unrealized_pnl_pct:.1%})")
        return await self._execute_sell(decision, forced=True)

    async def close_all_positions(self) -> None:
        """장 마감 전 전체 포지션 강제 청산"""
        logger.info(f"전체 포지션 청산 시작: {len(self.portfolio._positions)}개")
        for code, position in list(self.portfolio._positions.items()):
            decision = TradingDecision(
                stock_code=code,
                stock_name=position.name,
                final_action=Action.SELL,
                combined_confidence=1.0,
                gpt_result=None,
                gemini_result=None,
                consensus=False,
                target_price=position.current_price,
                stop_loss_price=position.current_price,
                reasoning_summary="장 마감 청산",
            )
            await self._execute_sell(decision, forced=True)
