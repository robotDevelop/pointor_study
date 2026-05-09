import logging
from typing import Dict, List

from src.kiwoom.api import KiwoomAPI
from src.kiwoom.constants import Market

logger = logging.getLogger(__name__)

# 키움 API 장애 시 사용할 기본 인기 종목 목록
FALLBACK_TOP20: List[Dict[str, str]] = [
    {"code": "005930", "name": "삼성전자"},
    {"code": "000660", "name": "SK하이닉스"},
    {"code": "035420", "name": "NAVER"},
    {"code": "005380", "name": "현대차"},
    {"code": "035720", "name": "카카오"},
    {"code": "051910", "name": "LG화학"},
    {"code": "006400", "name": "삼성SDI"},
    {"code": "068270", "name": "셀트리온"},
    {"code": "105560", "name": "KB금융"},
    {"code": "055550", "name": "신한지주"},
    {"code": "032830", "name": "삼성생명"},
    {"code": "003550", "name": "LG"},
    {"code": "096770", "name": "SK이노베이션"},
    {"code": "017670", "name": "SK텔레콤"},
    {"code": "030200", "name": "KT"},
    {"code": "012330", "name": "현대모비스"},
    {"code": "028260", "name": "삼성물산"},
    {"code": "066570", "name": "LG전자"},
    {"code": "316140", "name": "우리금융지주"},
    {"code": "018260", "name": "삼성에스디에스"},
]


class StockSelector:
    """
    키움 API에서 인기 종목 20개를 동적으로 가져온다.
    거래량 순위(60%) + 외국인/기관 순매수 순위(40%) 합산으로 최종 선정.
    """

    VOLUME_WEIGHT  = 0.6
    NETBUY_WEIGHT  = 0.4

    def __init__(self, kiwoom: KiwoomAPI):
        self.kiwoom = kiwoom

    def get_top_stocks(self, top_n: int = 20) -> List[Dict[str, str]]:
        try:
            volume_stocks = self.kiwoom.get_popular_stocks(top_n=top_n * 2)
            netbuy_stocks = self.kiwoom.get_net_buy_stocks(top_n=top_n * 2)
            merged = self._rank_and_merge(volume_stocks, netbuy_stocks, top_n)
            logger.info(f"인기 종목 {len(merged)}개 선정: {[s['name'] for s in merged]}")
            return merged
        except Exception as e:
            logger.warning(f"동적 종목 조회 실패, 기본 목록 사용: {e}")
            return FALLBACK_TOP20[:top_n]

    def _rank_and_merge(
        self,
        volume_list: List[Dict],
        netbuy_list: List[Dict],
        top_n: int,
    ) -> List[Dict[str, str]]:
        scores: Dict[str, float] = {}
        names: Dict[str, str] = {}

        for rank, stock in enumerate(volume_list, start=1):
            code = stock["code"]
            scores[code] = scores.get(code, 0) + (1 / rank) * self.VOLUME_WEIGHT
            names[code] = stock["name"]

        for rank, stock in enumerate(netbuy_list, start=1):
            code = stock["code"]
            scores[code] = scores.get(code, 0) + (1 / rank) * self.NETBUY_WEIGHT
            if code not in names:
                names[code] = stock["name"]

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [{"code": code, "name": names[code]} for code, _ in ranked[:top_n]]
