from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List


class Action(str, Enum):
    BUY  = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


@dataclass
class AnalysisResult:
    stock_code: str
    stock_name: str
    action: Action
    confidence: float            # 0.0 ~ 1.0
    target_price: int
    stop_loss_price: int
    holding_period_days: int
    reasoning: str
    risk_factors: List[str] = field(default_factory=list)
    bullish_signals: List[str] = field(default_factory=list)
    bearish_signals: List[str] = field(default_factory=list)
    model_name: str = ""
    latency_ms: float = 0.0


class BaseAnalyzer(ABC):
    @abstractmethod
    async def analyze(self, stock_data: "StockData") -> AnalysisResult:
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        pass
