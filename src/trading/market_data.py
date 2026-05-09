import logging
from dataclasses import dataclass
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from src.kiwoom.api import KiwoomAPI
from src.utils.time_utils import today_str, days_ago_str

logger = logging.getLogger(__name__)


@dataclass
class StockData:
    """AI 분석에 필요한 종목 데이터 전체"""
    code: str
    name: str
    current_price: int
    market_cap: str
    per: str
    pbr: str
    eps: str
    rsi: float
    macd: float
    macd_signal: float
    bb_upper: int
    bb_middle: int
    bb_lower: int
    ma5: int
    ma20: int
    ma60: int
    today_volume: int
    avg_volume: int
    volume_ratio: float
    ohlcv_df: pd.DataFrame

    def to_prompt_dict(self) -> Dict[str, Any]:
        return {
            "stock_code":    self.code,
            "stock_name":    self.name,
            "current_price": self.current_price,
            "market_cap":    self.market_cap,
            "rsi":           self.rsi,
            "macd":          self.macd,
            "macd_signal":   self.macd_signal,
            "bb_upper":      self.bb_upper,
            "bb_middle":     self.bb_middle,
            "bb_lower":      self.bb_lower,
            "ma5":           self.ma5,
            "ma20":          self.ma20,
            "ma60":          self.ma60,
            "today_volume":  self.today_volume,
            "avg_volume":    self.avg_volume,
            "volume_ratio":  self.volume_ratio,
            "per":           self.per,
            "pbr":           self.pbr,
            "eps":           self.eps,
            "ohlcv_table":   self.ohlcv_df.tail(30).to_string(index=False),
        }


class MarketDataFetcher:
    """키움 API에서 OHLCV를 가져와 기술적 지표를 계산한다."""

    def __init__(self, kiwoom: KiwoomAPI):
        self.kiwoom = kiwoom

    def fetch_stock_data(self, stock_code: str, stock_name: str) -> StockData:
        info = self.kiwoom.get_stock_info(stock_code)
        raw_ohlcv = self.kiwoom.get_daily_ohlcv(
            stock_code,
            start_date=days_ago_str(120),
            end_date=today_str(),
        )
        df = self._to_dataframe(raw_ohlcv)
        indicators = self._compute_indicators(df)

        return StockData(
            code=stock_code,
            name=stock_name,
            current_price=int(info.get("current_price", "0").replace(",", "") or 0),
            market_cap=info.get("market_cap", ""),
            per=info.get("per", "N/A"),
            pbr=info.get("pbr", "N/A"),
            eps=info.get("eps", "N/A"),
            ohlcv_df=df,
            **indicators,
        )

    def _to_dataframe(self, ohlcv: List[Dict]) -> pd.DataFrame:
        if not ohlcv:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        df = pd.DataFrame(ohlcv)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col].str.replace(",", ""), errors="coerce").fillna(0)
        df = df.sort_values("date").reset_index(drop=True)
        return df

    def _compute_indicators(self, df: pd.DataFrame) -> Dict[str, Any]:
        close  = df["close"].astype(float)
        volume = df["volume"].astype(float)

        rsi           = self._rsi(close)
        macd, signal  = self._macd(close)
        bb_u, bb_m, bb_l = self._bollinger(close)

        ma5_val  = close.rolling(5).mean().iloc[-1]  if len(close) >= 5  else close.iloc[-1]
        ma20_val = close.rolling(20).mean().iloc[-1] if len(close) >= 20 else close.iloc[-1]
        ma60_val = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else close.iloc[-1]

        avg_vol = volume.rolling(20).mean().iloc[-1] if len(volume) >= 20 else volume.mean()
        today_vol = volume.iloc[-1]

        return {
            "rsi":          round(rsi, 2),
            "macd":         round(macd, 4),
            "macd_signal":  round(signal, 4),
            "bb_upper":     int(bb_u),
            "bb_middle":    int(bb_m),
            "bb_lower":     int(bb_l),
            "ma5":          int(ma5_val),
            "ma20":         int(ma20_val),
            "ma60":         int(ma60_val),
            "today_volume": int(today_vol),
            "avg_volume":   int(avg_vol),
            "volume_ratio": round(today_vol / avg_vol * 100, 1) if avg_vol > 0 else 0.0,
        }

    @staticmethod
    def _rsi(close: pd.Series, period: int = 14) -> float:
        if len(close) < period + 1:
            return 50.0
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = 100 - 100 / (1 + rs)
        return float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50.0

    @staticmethod
    def _macd(close: pd.Series) -> tuple:
        if len(close) < 26:
            return 0.0, 0.0
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd  = ema12 - ema26
        sig   = macd.ewm(span=9, adjust=False).mean()
        return float(macd.iloc[-1]), float(sig.iloc[-1])

    @staticmethod
    def _bollinger(close: pd.Series, period: int = 20, mult: float = 2.0) -> tuple:
        if len(close) < period:
            price = float(close.iloc[-1])
            return price, price, price
        mid = close.rolling(period).mean()
        std = close.rolling(period).std()
        return (
            float(mid.iloc[-1] + mult * std.iloc[-1]),
            float(mid.iloc[-1]),
            float(mid.iloc[-1] - mult * std.iloc[-1]),
        )
