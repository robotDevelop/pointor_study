import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional

from src.kiwoom.api import KiwoomAPI

logger = logging.getLogger(__name__)


@dataclass
class Position:
    code: str
    name: str
    quantity: int
    avg_buy_price: int
    current_price: int
    buy_time: str  # ISO format string
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0

    def update_price(self, current_price: int) -> None:
        self.current_price = current_price
        if self.avg_buy_price > 0:
            self.unrealized_pnl = (current_price - self.avg_buy_price) * self.quantity
            self.unrealized_pnl_pct = (current_price - self.avg_buy_price) / self.avg_buy_price


@dataclass
class TradeRecord:
    code: str
    name: str
    action: str       # "BUY" / "SELL"
    quantity: int
    price: int
    timestamp: str    # ISO format string
    ai_action: str
    ai_confidence: float
    pnl: float = 0.0


class PortfolioManager:
    def __init__(self, kiwoom: KiwoomAPI, account_no: str, account_pw: str, data_dir: str = "data"):
        self.kiwoom = kiwoom
        self.account_no = account_no
        self.account_pw = account_pw
        self.data_dir = data_dir
        self._positions: Dict[str, Position] = {}
        self._trade_history: List[TradeRecord] = []
        self._cash: int = 0
        self._total_value: int = 0

    async def sync_from_kiwoom(self) -> None:
        """키움 API에서 실제 잔고를 가져와 포트폴리오를 동기화한다."""
        try:
            balance = await self.kiwoom.get_account_balance(self.account_no, self.account_pw)
            summary = balance["summary"]
            self._cash = int(summary.get("deposit", "0").replace(",", "") or 0)
            self._total_value = int(summary.get("total_evaluate", "0").replace(",", "") or 0)

            synced_codes = set()
            for pos_data in balance["positions"]:
                code = pos_data["code"]
                synced_codes.add(code)
                self._positions[code] = Position(
                    code=code,
                    name=pos_data["name"],
                    quantity=int(pos_data.get("quantity", 0)),
                    avg_buy_price=int(pos_data.get("avg_price", "0").replace(",", "") or 0),
                    current_price=int(pos_data.get("current_price", "0").replace(",", "") or 0),
                    buy_time=self._positions.get(code, Position(
                        code, "", 0, 0, 0, datetime.now().isoformat()
                    )).buy_time,
                )

            # 키움에 없는 포지션 제거
            for code in list(self._positions.keys()):
                if code not in synced_codes:
                    del self._positions[code]

            logger.info(
                f"포트폴리오 동기화: 예수금={self._cash:,}원, "
                f"평가금액={self._total_value:,}원, "
                f"보유종목={len(self._positions)}개"
            )
        except Exception as e:
            logger.error(f"포트폴리오 동기화 실패: {e}")

    def add_position(self, position: Position) -> None:
        self._positions[position.code] = position

    def remove_position(self, code: str) -> Optional[Position]:
        return self._positions.pop(code, None)

    def get_position(self, code: str) -> Optional[Position]:
        return self._positions.get(code)

    def has_position(self, code: str) -> bool:
        return code in self._positions

    def get_total_exposure(self) -> float:
        if self._total_value <= 0:
            return 0.0
        invested = sum(p.quantity * p.current_price for p in self._positions.values())
        return invested / self._total_value

    def get_positions_value(self) -> Dict[str, int]:
        return {code: p.quantity * p.current_price for code, p in self._positions.items()}

    def record_trade(self, record: TradeRecord) -> None:
        self._trade_history.append(record)
        logger.info(
            f"매매 기록: {record.action} {record.name}({record.code}) "
            f"x{record.quantity} @ {record.price:,}원 (AI신뢰도={record.ai_confidence:.2f})"
        )

    def save_state(self) -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        path = os.path.join(self.data_dir, "portfolio_state.json")
        state = {
            "positions": {code: asdict(p) for code, p in self._positions.items()},
            "cash": self._cash,
            "total_value": self._total_value,
            "trade_history": [asdict(t) for t in self._trade_history[-100:]],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def load_state(self) -> None:
        path = os.path.join(self.data_dir, "portfolio_state.json")
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        self._cash = state.get("cash", 0)
        self._total_value = state.get("total_value", 0)
        for code, p_data in state.get("positions", {}).items():
            self._positions[code] = Position(**p_data)
        logger.info(f"포트폴리오 상태 복원: {len(self._positions)}개 포지션")
