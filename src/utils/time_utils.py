from datetime import datetime, date, timedelta
import pytz

KST = pytz.timezone("Asia/Seoul")


def now_kst() -> datetime:
    return datetime.now(KST)


def today_str() -> str:
    return now_kst().strftime("%Y%m%d")


def days_ago_str(n: int) -> str:
    d = now_kst().date() - timedelta(days=n)
    return d.strftime("%Y%m%d")


def is_market_open() -> bool:
    now = now_kst()
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=5, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=20, second=0, microsecond=0)
    return market_open <= now <= market_close


def is_pre_close(minutes_before: int = 30) -> bool:
    now = now_kst()
    threshold = now.replace(hour=15, minute=0, second=0, microsecond=0) - timedelta(minutes=minutes_before)
    close = now.replace(hour=15, minute=0, second=0, microsecond=0)
    return threshold <= now <= close
