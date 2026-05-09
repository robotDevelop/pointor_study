import logging
from typing import Any, Callable, Dict, List, Optional

from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QEventLoop

from config.settings import KiwoomConfig
from src.kiwoom.constants import FID, OrderType, PriceType, Screen, TR
from src.kiwoom.exceptions import KiwoomLoginError, KiwoomOrderError, KiwoomTRError
from src.utils.rate_limiter import RateLimiter
from src.utils.time_utils import today_str, days_ago_str

logger = logging.getLogger(__name__)


class KiwoomAPI(QAxWidget):
    """
    키움 OpenAPI+ COM 컨트롤 래퍼.
    모든 TR 요청은 CommRqData → QEventLoop.exec_() → OnReceiveTrData 콜백 패턴으로 동기화한다.
    """

    CLSID = "{A1574A0D-6BFA-4BD7-9020-DED88711818D}"

    def __init__(self, config: KiwoomConfig):
        super().__init__()
        self.setControl(self.CLSID)
        self.config = config
        self._rate_limiter = RateLimiter(
            tr_delay=config.tr_delay_ms / 1000.0,
            real_delay=config.real_delay_ms / 1000.0,
        )
        self._login_loop = QEventLoop()
        self._tr_loop = QEventLoop()
        self._tr_data: Dict[str, Any] = {}
        self._real_callbacks: Dict[str, Callable] = {}
        self._connect_signals()

    # ──────────────────────────────────────────────────────────────
    # 시그널 연결
    # ──────────────────────────────────────────────────────────────
    def _connect_signals(self) -> None:
        self.OnEventConnect.connect(self._on_event_connect)
        self.OnReceiveTrData.connect(self._on_receive_tr_data)
        self.OnReceiveRealData.connect(self._on_receive_real_data)
        self.OnReceiveChejanData.connect(self._on_receive_chejan_data)
        self.OnReceiveMsg.connect(self._on_receive_msg)

    # ──────────────────────────────────────────────────────────────
    # 로그인
    # ──────────────────────────────────────────────────────────────
    def login(self) -> bool:
        self.dynamicCall("CommConnect()")
        self._login_loop.exec_()
        return self.get_connect_state() == 1

    def logout(self) -> None:
        self.dynamicCall("CommTerminate()")

    def get_connect_state(self) -> int:
        return self.dynamicCall("GetConnectState()")

    # ──────────────────────────────────────────────────────────────
    # TR 요청 코어
    # ──────────────────────────────────────────────────────────────
    def _send_tr(
        self,
        rq_name: str,
        tr_code: str,
        screen_no: str,
        inputs: Dict[str, str],
        prev_next: int = 0,
    ) -> Dict[str, Any]:
        self._rate_limiter.wait_tr()
        for key, value in inputs.items():
            self.dynamicCall("SetInputValue(QString, QString)", key, value)
        ret = self.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            rq_name, tr_code, prev_next, screen_no,
        )
        if ret != 0:
            raise KiwoomTRError(f"CommRqData 오류 {ret}: {tr_code}")
        self._tr_data = {}
        self._tr_loop.exec_()
        return self._tr_data

    def get_comm_data(self, tr_code: str, record_name: str, index: int, item_name: str) -> str:
        return self.dynamicCall(
            "GetCommData(QString, QString, int, QString)",
            tr_code, record_name, index, item_name,
        ).strip()

    def get_repeat_cnt(self, tr_code: str, record_name: str) -> int:
        return self.dynamicCall("GetRepeatCnt(QString, QString)", tr_code, record_name)

    # ──────────────────────────────────────────────────────────────
    # 콜백 슬롯
    # ──────────────────────────────────────────────────────────────
    def _on_event_connect(self, err_code: int) -> None:
        if err_code == 0:
            logger.info("키움 로그인 성공")
        else:
            logger.error(f"키움 로그인 실패: {err_code}")
        self._login_loop.exit(err_code)

    def _on_receive_tr_data(
        self, screen_no, rq_name, tr_code, record_name,
        prev_next, data_len, err_code, msg, spl_msg,
    ) -> None:
        self._tr_data = {
            "tr_code": tr_code,
            "record_name": record_name,
            "prev_next": prev_next,
        }
        self._tr_loop.exit(0)

    def _on_receive_real_data(self, code: str, real_type: str, real_data: str) -> None:
        if real_type in self._real_callbacks:
            self._real_callbacks[real_type](code, real_data)

    def _on_receive_chejan_data(self, gubun: str, item_cnt: int, fid_list: str) -> None:
        data = {}
        for fid in fid_list.split(";"):
            if fid:
                data[fid] = self.dynamicCall("GetChejanData(int)", int(fid))
        logger.debug(f"체결잔고 수신: gubun={gubun}, 데이터={data}")

    def _on_receive_msg(self, screen_no, rq_name, tr_code, msg) -> None:
        logger.debug(f"키움 메시지 [{tr_code}]: {msg}")

    # ──────────────────────────────────────────────────────────────
    # 종목 정보 조회
    # ──────────────────────────────────────────────────────────────
    def get_popular_stocks(self, top_n: int = 20, market: str = "001") -> List[Dict[str, str]]:
        """OPT10030: 거래량 상위 종목 조회"""
        self._send_tr(
            rq_name="거래량상위요청",
            tr_code=TR.VOLUME_RANK,
            screen_no=Screen.POPULAR_STOCKS,
            inputs={
                "시장구분": market,
                "정렬구분": "1",       # 1: 거래량, 2: 거래대금
                "관리종목포함": "0",
                "신용구분": "0",
                "거래량구분": "5",
            },
        )
        tr_code = TR.VOLUME_RANK
        record_name = "거래량상위요청"
        count = min(self.get_repeat_cnt(tr_code, record_name), top_n)
        stocks = []
        for i in range(count):
            code = self.get_comm_data(tr_code, record_name, i, "종목코드").lstrip("A")
            name = self.get_comm_data(tr_code, record_name, i, "종목명")
            price = self.get_comm_data(tr_code, record_name, i, "현재가").lstrip("+-")
            volume = self.get_comm_data(tr_code, record_name, i, "거래량")
            if code:
                stocks.append({"code": code, "name": name, "price": price, "volume": volume})
        return stocks

    def get_net_buy_stocks(self, top_n: int = 40, market: str = "001") -> List[Dict[str, str]]:
        """OPT10023: 외국인/기관 순매수 상위 종목"""
        self._send_tr(
            rq_name="외국인기관순매수",
            tr_code=TR.NET_BUY_RANK,
            screen_no=Screen.POPULAR_STOCKS,
            inputs={
                "시장구분": market,
                "날짜": today_str(),
                "금액수량구분": "1",   # 1: 금액
                "매매구분": "0",       # 0: 순매수
                "단위구분": "1000",
            },
        )
        tr_code = TR.NET_BUY_RANK
        record_name = "외국인기관순매수"
        count = min(self.get_repeat_cnt(tr_code, record_name), top_n)
        stocks = []
        for i in range(count):
            code = self.get_comm_data(tr_code, record_name, i, "종목코드").lstrip("A")
            name = self.get_comm_data(tr_code, record_name, i, "종목명")
            if code:
                stocks.append({"code": code, "name": name})
        return stocks

    def get_stock_info(self, stock_code: str) -> Dict[str, Any]:
        """OPT10001: 주식 기본정보 (현재가, PER, PBR, EPS, 시가총액)"""
        self._send_tr(
            rq_name="주식기본정보요청",
            tr_code=TR.STOCK_BASIC_INFO,
            screen_no=Screen.REAL_TIME,
            inputs={"종목코드": stock_code},
        )
        tr_code = TR.STOCK_BASIC_INFO
        record_name = "주식기본정보요청"

        def _get(item: str) -> str:
            return self.get_comm_data(tr_code, record_name, 0, item).lstrip("+-")

        return {
            "code": stock_code,
            "name": _get("종목명"),
            "current_price": _get("현재가"),
            "market_cap": _get("시가총액"),
            "per": _get("PER"),
            "pbr": _get("PBR"),
            "eps": _get("EPS"),
            "listed_shares": _get("상장주식"),
            "face_value": _get("액면가"),
        }

    def get_daily_ohlcv(
        self, stock_code: str, start_date: str = "", end_date: str = ""
    ) -> List[Dict[str, str]]:
        """OPT10081: 일봉차트 데이터 (페이지네이션 처리)"""
        if not end_date:
            end_date = today_str()
        if not start_date:
            start_date = days_ago_str(120)

        all_rows: List[Dict[str, str]] = []
        prev_next = 0

        while True:
            self._send_tr(
                rq_name="일봉차트요청",
                tr_code=TR.DAILY_OHLCV,
                screen_no=Screen.REAL_TIME,
                inputs={
                    "종목코드": stock_code,
                    "기준일자": end_date,
                    "수정주가구분": "1",
                },
                prev_next=prev_next,
            )
            tr_code = TR.DAILY_OHLCV
            record_name = "일봉차트요청"
            count = self.get_repeat_cnt(tr_code, record_name)

            for i in range(count):
                row = {
                    "date":   self.get_comm_data(tr_code, record_name, i, "일자"),
                    "open":   self.get_comm_data(tr_code, record_name, i, "시가").lstrip("+-"),
                    "high":   self.get_comm_data(tr_code, record_name, i, "고가").lstrip("+-"),
                    "low":    self.get_comm_data(tr_code, record_name, i, "저가").lstrip("+-"),
                    "close":  self.get_comm_data(tr_code, record_name, i, "현재가").lstrip("+-"),
                    "volume": self.get_comm_data(tr_code, record_name, i, "거래량"),
                }
                if row["date"] >= start_date:
                    all_rows.append(row)
                else:
                    return all_rows

            if self._tr_data.get("prev_next") != "2":
                break
            prev_next = 2

        return all_rows

    def get_account_balance(self, account_no: str, password: str) -> Dict[str, Any]:
        """OPW00004: 계좌 평가 잔고 내역"""
        self._send_tr(
            rq_name="계좌평가잔고내역요청",
            tr_code=TR.ACCOUNT_BALANCE,
            screen_no=Screen.PORTFOLIO,
            inputs={
                "계좌번호": account_no,
                "비밀번호": password,
                "비밀번호입력매체구분": "00",
                "조회구분": "2",
            },
        )
        tr_code = TR.ACCOUNT_BALANCE
        record_name = "계좌평가잔고내역요청"

        def _single(item: str) -> str:
            return self.get_comm_data(tr_code, "계좌평가결과", 0, item).lstrip("+-")

        summary = {
            "total_purchase": _single("매입금액"),
            "total_evaluate": _single("평가금액"),
            "total_profit": _single("평가손익합계"),
            "profit_rate": _single("수익률(%%)"),
            "deposit": _single("예수금"),
        }

        count = self.get_repeat_cnt(tr_code, record_name)
        positions = []
        for i in range(count):
            def _get(item: str) -> str:
                return self.get_comm_data(tr_code, record_name, i, item).lstrip("+-")
            code = _get("종목번호").lstrip("A")
            if code:
                positions.append({
                    "code": code,
                    "name": _get("종목명"),
                    "quantity": _get("보유수량"),
                    "avg_price": _get("매입가"),
                    "current_price": _get("현재가"),
                    "evaluate_amount": _get("평가금액"),
                    "profit_loss": _get("평가손익"),
                    "profit_rate": _get("수익률(%%)"),
                })

        return {"summary": summary, "positions": positions}

    def get_deposit(self, account_no: str, password: str) -> int:
        """OPWPOA21: 주문 가능 예수금"""
        self._send_tr(
            rq_name="예수금상세현황요청",
            tr_code=TR.ACCOUNT_DEPOSIT,
            screen_no=Screen.PORTFOLIO,
            inputs={
                "계좌번호": account_no,
                "비밀번호": password,
                "비밀번호입력매체구분": "00",
                "조회구분": "2",
            },
        )
        raw = self.get_comm_data(TR.ACCOUNT_DEPOSIT, "예수금상세현황요청", 0, "주문가능금액")
        return int(raw.lstrip("+-").replace(",", "") or "0")

    def place_order(
        self,
        order_type: int,
        stock_code: str,
        quantity: int,
        price: int,
        account_no: str,
        price_type: str = PriceType.MARKET,
        original_order_no: str = "",
    ) -> str:
        """SendOrder: 주식 주문 (매수/매도/취소/정정)"""
        ret = self.dynamicCall(
            "SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
            "주식주문",
            Screen.ORDER,
            account_no,
            order_type,
            stock_code,
            quantity,
            price,
            price_type,
            original_order_no,
        )
        if ret != 0:
            raise KiwoomOrderError(f"SendOrder 오류 {ret}: {stock_code} {quantity}주")
        logger.info(
            f"주문 전송: {'매수' if order_type == OrderType.BUY else '매도'} "
            f"{stock_code} {quantity}주 @ {'시장가' if price == 0 else f'{price:,}원'}"
        )
        return ""  # 실제 주문번호는 OnReceiveChejanData에서 수신

    def register_real_time(
        self,
        screen_no: str,
        stock_codes: List[str],
        fid_list: List[int],
        real_type: str = "0",
    ) -> None:
        self._rate_limiter.wait_real()
        codes_str = ";".join(stock_codes)
        fids_str = ";".join(str(f) for f in fid_list)
        self.dynamicCall(
            "SetRealReg(QString, QString, QString, QString)",
            screen_no, codes_str, fids_str, real_type,
        )

    def unregister_real_time(self, screen_no: str, stock_code: str = "") -> None:
        self.dynamicCall("SetRealRemove(QString, QString)", screen_no, stock_code or "ALL")

    def register_real_callback(self, real_type: str, callback: Callable) -> None:
        self._real_callbacks[real_type] = callback

    def get_master_stock_name(self, stock_code: str) -> str:
        return self.dynamicCall("GetMasterStockName(QString)", stock_code)
