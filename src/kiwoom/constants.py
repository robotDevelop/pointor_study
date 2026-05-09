class TR:
    VOLUME_RANK         = "OPT10030"  # 거래량 상위 종목
    NET_BUY_RANK        = "OPT10023"  # 투자자별 순매수 상위
    STOCK_BASIC_INFO    = "OPT10001"  # 주식 기본정보
    DAILY_OHLCV         = "OPT10081"  # 주식 일봉차트
    MINUTE_OHLCV        = "OPT10080"  # 주식 분봉차트
    ACCOUNT_BALANCE     = "OPW00004"  # 계좌평가잔고내역
    ACCOUNT_DEPOSIT     = "OPWPOA21"  # 예수금 상세현황
    UNFILLED_ORDERS     = "OPT10075"  # 미체결 조회
    FILLED_ORDERS       = "OPT10076"  # 체결 내역


class FID:
    CURRENT_PRICE   = 10
    VOLUME          = 15
    OPEN_PRICE      = 16
    HIGH_PRICE      = 17
    LOW_PRICE       = 18
    BUY_PRICE_1     = 41
    SELL_PRICE_1    = 51
    BUY_VOLUME_1    = 61
    SELL_VOLUME_1   = 71
    MARKET_CAP      = 311

    REAL_TIME_FIDS = [10, 15, 16, 17, 18, 41, 51]


class OrderType:
    BUY         = 1   # 신규매수
    SELL        = 2   # 신규매도
    CANCEL_BUY  = 3   # 매수취소
    CANCEL_SELL = 4   # 매도취소
    MODIFY_BUY  = 5   # 매수정정
    MODIFY_SELL = 6   # 매도정정


class PriceType:
    LIMIT       = "00"  # 지정가
    MARKET      = "03"  # 시장가
    BEST        = "05"  # 최유리지정가
    IMMEDIATE   = "06"  # 최우선지정가


class RealType:
    STOCK_TICK  = "주식체결"
    ORDER_FILL  = "주식주문체결"
    BID_ASK     = "주식호가잔량"
    BALANCE     = "잔고"


class Screen:
    POPULAR_STOCKS  = "2000"
    REAL_TIME       = "3000"
    ORDER           = "4000"
    PORTFOLIO       = "5000"


class Market:
    KOSPI   = "001"
    KOSDAQ  = "101"
    ALL     = ""
