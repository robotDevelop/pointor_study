import logging
import os
import sys
from datetime import datetime


def setup_logging(log_level: str = "INFO", log_dir: str = "logs") -> None:
    os.makedirs(log_dir, exist_ok=True)

    level = getattr(logging, log_level.upper(), logging.INFO)
    log_file = os.path.join(log_dir, f"trading_{datetime.now().strftime('%Y%m%d')}.log")

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers)

    # 외부 라이브러리 로그 레벨 조정
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
