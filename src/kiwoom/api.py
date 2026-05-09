"""
키움증권 REST API 클라이언트 (Linux/Mac/Windows 공통)
- COM/QAxWidget 없이 순수 HTTP 방식
- 키움 개발자 포털: https://apiportal.kiwoom.com
- 토큰 자동 갱신, 속도 제한 내장
"""
import asyncio
import logging
import time as _time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import httpx

from config.settings import KiwoomConfig
from src.kiwoom.constants import OrderType, PriceType, Screen
from src.kiwoom.exceptions import KiwoomLoginError, KiwoomOrderError, KiwoomTRError
from src.utils.rate_limiter import RateLimiter
from src.utils.time_utils import today_str, days_ago_str

logger = logging.getLogger(__name__)

# 실시간 콜백 타입
RealCallback = Callable[[str, Dict[str, str]], None]


class KiwoomAPI:
    """
    키움증권 REST API 비동기 클라이언트.

    토큰은 발급 후 내부적으로 캐시하며 만료 10분 전에 자동 갱신한다.
    모든 TR 요청은 속도 제한(0.2초 간격)이 적용된다.
    """

    TOKEN_PATH    = "/oauth2/token"
    PRICE_PATH    = "/uapi/domestic-stock/v1/quotations/inquire-price"
    DAILY_PATH    = "/uapi/domestic-stock/v1/quotations/inquire-daily-price"
    VOLUME_PATH   = "/uapi/domestic-stock/v1/ranking/volume"
    NETBUY_PATH   = "/uapi/domestic-stock/v1/ranking/investor-netbuy"
    INFO_PATH     = "/uapi/domestic-stock/v1/quotations/search-stock-info"
    ORDER_PATH    = "/uapi/domestic-stock/v1/trading/order-cash"
    BALANCE_PATH  = "/uapi/domestic-stock/v1/trading/inquire-balance"
    DEPOSIT_PATH  = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"

    def __init__(self, config: KiwoomConfig):
        self.config = config
        self._rate_limiter = RateLimiter(tr_delay=config.tr_delay_ms / 1000.0)
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._client: Optional[httpx.AsyncClient] = None
        self._real_callbacks: Dict[str, RealCallback] = {}

    # ──────────────────────────────────────────────────────────────
    # 세션 관리
    # ──────────────────────────────────────────────────────────────
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=30.0,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ──────────────────────────────────────────────────────────────
    # 인증 / 토큰 관리
    # ──────────────────────────────────────────────────────────────
    async def login(self) -> bool:
        try:
            await self._refresh_token()
            logger.info("키움 REST API 로그인 성공")
            return True
        except Exception as e:
            logger.error(f"키움 REST API 로그인 실패: {e}")
            return False

    async def logout(self) -> None:
        await self.close()
        self._token = None

    async def _refresh_token(self) -> None:
        client = await self._get_client()
        resp = await client.post(
            self.TOKEN_PATH,
            json={
                "grant_type": "client_credentials",
                "appkey": self.config.app_key,
                "secretkey": self.config.app_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        expires_in = int(data.get("expires_in", 86400))
        self._token_expires_at = _time.monotonic() + expires_in - 600  # 10분 전 갱신

    async def _get_token(self) -> str:
        if self._token is None or _time.monotonic() >= self._token_expires_at:
            await self._refresh_token()
        return self._token  # type: ignore[return-value]

    def get_connect_state(self) -> int:
        return 1 if self._token else 0

    # ──────────────────────────────────────────────────────────────
    # HTTP 요청 헬퍼
    # ──────────────────────────────────────────────────────────────
    async def _get(self, path: str, params: Dict[str, str], tr_id: str) -> Dict:
        self._rate_limiter.wait_tr()
        token = await self._get_token()
        client = await self._get_client()
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        try:
            resp = await client.get(path, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            raise KiwoomTRError(f"HTTP {e.response.status_code}: {e.response.text}") from e

    async def _post(self, path: str, body: Dict, tr_id: str) -> Dict:
        self._rate_limiter.wait_tr()
        token = await self._get_token()
        client = await self._get_client()
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        try:
            resp = await client.post(path, json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            raise KiwoomOrderError(f"HTTP {e.response.status_code}: {e.response.text}") from e

    # ──────────────────────────────────────────────────────────────
    # 시장 데이터
    # ──────────────────────────────────────────────────────────────
    async def get_popular_stocks(self, top_n: int = 20, market: str = "J") -> List[Dict[str, str]]:
        """거래량 상위 종목 조회"""
        data = await self._get(
            self.VOLUME_PATH,
            params={
                "FID_COND_MRKT_DIV_CODE": market,
                "FID_COND_SCR_DIV_CODE": "20171",
                "FID_INPUT_ISCD": "0000",
                "FID_DIV_CLS_CODE": "0",
                "FID_BLNG_CLS_CODE": "0",
                "FID_TRGT_CLS_CODE": "111111111",
                "FID_TRGT_EXLS_CLS_CODE": "0000000000",
                "FID_INPUT_PRICE_1": "",
                "FID_INPUT_PRICE_2": "",
                "FID_VOL_CNT": str(top_n),
                "FID_INPUT_DATE_1": "",
            },
            tr_id="FHPST01710000",
        )
        output = data.get("output", [])
        return [
            {
                "code":   item.get("mksc_shrn_iscd", "").lstrip("A"),
                "name":   item.get("hts_kor_isnm", ""),
                "price":  item.get("stck_prpr", "0"),
                "volume": item.get("acml_vol", "0"),
            }
            for item in output[:top_n]
            if item.get("mksc_shrn_iscd")
        ]

    async def get_net_buy_stocks(self, top_n: int = 40, market: str = "J") -> List[Dict[str, str]]:
        """외국인/기관 순매수 상위 종목"""
        data = await self._get(
            self.NETBUY_PATH,
            params={
                "FID_COND_MRKT_DIV_CODE": market,
                "FID_COND_SCR_DIV_CODE": "20227",
                "FID_INPUT_ISCD": "0000",
                "FID_DIV_CLS_CODE": "0",
                "FID_BLNG_CLS_CODE": "0",
                "FID_TRGT_CLS_CODE": "111111111",
                "FID_TRGT_EXLS_CLS_CODE": "0000000000",
                "FID_INPUT_PRICE_1": "",
                "FID_INPUT_PRICE_2": "",
                "FID_VOL_CNT": str(top_n),
                "FID_INPUT_DATE_1": today_str(),
            },
            tr_id="FHPST02270000",
        )
        output = data.get("output", [])
        return [
            {
                "code": item.get("mksc_shrn_iscd", "").lstrip("A"),
                "name": item.get("hts_kor_isnm", ""),
            }
            for item in output[:top_n]
            if item.get("mksc_shrn_iscd")
        ]

    async def get_stock_info(self, stock_code: str) -> Dict[str, Any]:
        """주식 기본정보 (현재가, PER, PBR, EPS, 시가총액)"""
        data = await self._get(
            self.PRICE_PATH,
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": stock_code,
            },
            tr_id="FHKST01010100",
        )
        out = data.get("output", {})
        return {
            "code":          stock_code,
            "name":          out.get("hts_kor_isnm", ""),
            "current_price": out.get("stck_prpr", "0"),
            "market_cap":    out.get("hts_avls", ""),
            "per":           out.get("per", "N/A"),
            "pbr":           out.get("pbr", "N/A"),
            "eps":           out.get("eps", "N/A"),
            "listed_shares": out.get("lstn_stcn", ""),
            "face_value":    out.get("stck_fcam", ""),
        }

    async def get_daily_ohlcv(
        self, stock_code: str, start_date: str = "", end_date: str = ""
    ) -> List[Dict[str, str]]:
        """일봉 차트 조회 (최대 100일, 필요시 반복 호출)"""
        if not end_date:
            end_date = today_str()
        if not start_date:
            start_date = days_ago_str(120)

        all_rows: List[Dict[str, str]] = []
        period_divcode = "D"  # 일봉

        data = await self._get(
            self.DAILY_PATH,
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD":         stock_code,
                "FID_INPUT_DATE_1":       start_date,
                "FID_INPUT_DATE_2":       end_date,
                "FID_PERIOD_DIV_CODE":    period_divcode,
                "FID_ORG_ADJ_PRC":        "0",  # 수정주가 반영
            },
            tr_id="FHKST03010100",
        )
        output = data.get("output2", [])
        for item in output:
            date_val = item.get("stck_bsop_date", "")
            if date_val >= start_date:
                all_rows.append({
                    "date":   date_val,
                    "open":   item.get("stck_oprc", "0"),
                    "high":   item.get("stck_hgpr", "0"),
                    "low":    item.get("stck_lwpr", "0"),
                    "close":  item.get("stck_clpr", "0"),
                    "volume": item.get("acml_vol", "0"),
                })
        return all_rows

    async def get_account_balance(self, account_no: str, account_pw: str) -> Dict[str, Any]:
        """계좌 평가 잔고 조회"""
        data = await self._get(
            self.BALANCE_PATH,
            params={
                "CANO":          account_no[:8],
                "ACNT_PRDT_CD":  account_no[8:] if len(account_no) > 8 else "01",
                "AFHR_FLPR_YN":  "N",
                "OFL_YN":        "",
                "INQR_DVSN":     "02",
                "UNPR_DVSN":     "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN":     "01",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
            tr_id="TTTC8434R" if not self.config.is_simulated else "VTTC8434R",
        )
        output1 = data.get("output1", [])
        output2 = data.get("output2", {})

        positions = [
            {
                "code":            item.get("pdno", ""),
                "name":            item.get("prdt_name", ""),
                "quantity":        item.get("hldg_qty", "0"),
                "avg_price":       item.get("pchs_avg_pric", "0"),
                "current_price":   item.get("prpr", "0"),
                "evaluate_amount": item.get("evlu_amt", "0"),
                "profit_loss":     item.get("evlu_pfls_amt", "0"),
                "profit_rate":     item.get("evlu_pfls_rt", "0"),
            }
            for item in output1
            if item.get("pdno")
        ]

        summary = {
            "total_purchase": output2.get("pchs_amt_smtl_amt", "0"),
            "total_evaluate": output2.get("evlu_amt_smtl_amt", "0"),
            "total_profit":   output2.get("evlu_pfls_smtl_amt", "0"),
            "profit_rate":    output2.get("tot_evlu_pfls_rt", "0"),
            "deposit":        output2.get("dnca_tot_amt", "0"),
        }
        return {"summary": summary, "positions": positions}

    async def get_deposit(self, account_no: str, account_pw: str) -> int:
        """주문 가능 예수금"""
        data = await self._get(
            self.DEPOSIT_PATH,
            params={
                "CANO":         account_no[:8],
                "ACNT_PRDT_CD": account_no[8:] if len(account_no) > 8 else "01",
                "PDNO":         "005930",
                "ORD_UNPR":     "0",
                "ORD_DVSN":     "01",
                "CMA_EVLU_AMT_ICLD_YN": "Y",
                "OVRS_ICLD_YN": "N",
            },
            tr_id="TTTC8908R" if not self.config.is_simulated else "VTTC8908R",
        )
        raw = data.get("output", {}).get("ord_psbl_cash", "0")
        return int(raw.replace(",", "") or 0)

    async def place_order(
        self,
        order_type: int,
        stock_code: str,
        quantity: int,
        price: int,
        account_no: str,
        price_type: str = PriceType.MARKET,
        original_order_no: str = "",
    ) -> str:
        # 모의투자/실거래 TR ID 구분
        if not self.config.is_simulated:
            tr_id = "TTTC0802U" if order_type == OrderType.BUY else "TTTC0801U"
        else:
            tr_id = "VTTC0802U" if order_type == OrderType.BUY else "VTTC0801U"

        body = {
            "CANO":          account_no[:8],
            "ACNT_PRDT_CD":  account_no[8:] if len(account_no) > 8 else "01",
            "PDNO":          stock_code,
            "ORD_DVSN":      price_type,
            "ORD_QTY":       str(quantity),
            "ORD_UNPR":      str(price),
        }
        if original_order_no:
            body["ORGN_ODNO"] = original_order_no

        data = await self._post(self.ORDER_PATH, body, tr_id)
        order_no = data.get("output", {}).get("ODNO", "")
        logger.info(
            f"주문 완료: {'매수' if order_type == OrderType.BUY else '매도'} "
            f"{stock_code} {quantity}주 @ {'시장가' if price == 0 else f'{price:,}원'} "
            f"(주문번호={order_no})"
        )
        return order_no

    def register_real_callback(self, real_type: str, callback: RealCallback) -> None:
        self._real_callbacks[real_type] = callback

    def get_master_stock_name(self, stock_code: str) -> str:
        return ""  # REST 환경에서는 get_stock_info() 사용
