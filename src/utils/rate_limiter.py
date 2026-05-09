import time
import threading


class RateLimiter:
    """
    키움 API 요청 속도 제한.
    TR: 초당 5회(0.2초 간격), 실시간 등록/해제: 초당 2회(0.5초 간격)
    """

    def __init__(self, tr_delay: float = 0.2, real_delay: float = 0.5):
        self._tr_delay = tr_delay
        self._real_delay = real_delay
        self._last_tr = 0.0
        self._last_real = 0.0
        self._lock = threading.Lock()

    def wait_tr(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_tr
            if elapsed < self._tr_delay:
                time.sleep(self._tr_delay - elapsed)
            self._last_tr = time.monotonic()

    def wait_real(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_real
            if elapsed < self._real_delay:
                time.sleep(self._real_delay - elapsed)
            self._last_real = time.monotonic()
