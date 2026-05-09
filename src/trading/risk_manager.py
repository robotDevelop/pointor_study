import logging
from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional

from config.settings import RiskConfig

logger = logging.getLogger(__name__)


@dataclass
class RiskCheckResult:
    approved: bool
    reason: str
    adjusted_quantity: int


class RiskManager:
    """
    주문 전 리스크 규칙 검사.

    규칙:
    1. 종목당 투자비율 ≤ max_position_pct (10%)
    2. 총 투자비율 ≤ max_total_exposure_pct (50%)
    3. 동시 보유 종목 수 ≤ max_positions (5)
    4. AI 신뢰도 ≥ min_confidence (0.70)
    5. 손절: current_price ≤ avg_buy * (1 - stop_loss_pct)
    6. 익절: current_price ≥ avg_buy * (1 + take_profit_pct)
    7. 일일 매매 횟수 ≤ max_daily_trades (10)
    """

    def __init__(self, config: RiskConfig):
        self.config = config
        self._daily_trade_count: int = 0
        self._last_reset_date: Optional[date] = None

    def _auto_reset_daily(self) -> None:
        today = date.today()
        if self._last_reset_date != today:
            self._daily_trade_count = 0
            self._last_reset_date = today

    def check_buy(
        self,
        stock_code: str,
        current_price: int,
        portfolio_value: int,
        available_cash: int,
        current_positions: Dict[str, int],
        ai_confidence: float,
        allow_new_buys: bool = True,
    ) -> RiskCheckResult:
        self._auto_reset_daily()

        if not allow_new_buys:
            return RiskCheckResult(False, "신규 매수 중단 시간대", 0)

        if ai_confidence < self.config.min_confidence:
            return RiskCheckResult(False, f"AI 신뢰도 부족 ({ai_confidence:.2f} < {self.config.min_confidence})", 0)

        if self._daily_trade_count >= self.config.max_daily_trades:
            return RiskCheckResult(False, f"일일 매매 횟수 초과 ({self._daily_trade_count})", 0)

        if len(current_positions) >= self.config.max_positions:
            return RiskCheckResult(False, f"최대 보유 종목 수 초과 ({len(current_positions)})", 0)

        if stock_code in current_positions:
            return RiskCheckResult(False, "이미 보유 중인 종목", 0)

        if portfolio_value <= 0:
            return RiskCheckResult(False, "포트폴리오 가치 없음", 0)

        total_invested = sum(current_positions.values())
        total_exposure = total_invested / portfolio_value
        if total_exposure >= self.config.max_total_exposure_pct:
            return RiskCheckResult(False, f"총 투자비율 초과 ({total_exposure:.1%})", 0)

        max_invest = int(portfolio_value * self.config.max_position_pct)
        max_invest = min(max_invest, available_cash)
        if max_invest < current_price:
            return RiskCheckResult(False, "주문 가능 금액 부족", 0)

        quantity = max_invest // current_price
        if quantity <= 0:
            return RiskCheckResult(False, "계산된 수량 0", 0)

        return RiskCheckResult(True, "승인", quantity)

    def check_sell(
        self,
        stock_code: str,
        avg_buy_price: int,
        current_price: int,
        holding_quantity: int,
        forced: bool = False,
    ) -> RiskCheckResult:
        self._auto_reset_daily()

        if holding_quantity <= 0:
            return RiskCheckResult(False, "보유 수량 없음", 0)

        if forced:
            return RiskCheckResult(True, "강제 청산", holding_quantity)

        if self._daily_trade_count >= self.config.max_daily_trades:
            return RiskCheckResult(False, f"일일 매매 횟수 초과 ({self._daily_trade_count})", 0)

        return RiskCheckResult(True, "매도 승인", holding_quantity)

    def check_stop_loss(self, avg_buy_price: int, current_price: int) -> bool:
        if avg_buy_price <= 0:
            return False
        return current_price <= avg_buy_price * (1 - self.config.stop_loss_pct)

    def check_take_profit(self, avg_buy_price: int, current_price: int) -> bool:
        if avg_buy_price <= 0:
            return False
        return current_price >= avg_buy_price * (1 + self.config.take_profit_pct)

    def increment_trade_count(self) -> None:
        self._auto_reset_daily()
        self._daily_trade_count += 1
        logger.debug(f"일일 매매 횟수: {self._daily_trade_count}/{self.config.max_daily_trades}")

    def reset_daily_counters(self) -> None:
        self._daily_trade_count = 0
        self._last_reset_date = date.today()
        logger.info("일일 카운터 초기화 완료")
