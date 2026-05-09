import os
from dataclasses import dataclass, field
from typing import Optional

import yaml
from dotenv import load_dotenv


@dataclass
class KiwoomConfig:
    # REST API 인증 (키움 개발자 포털에서 발급)
    app_key: str = ""
    app_secret: str = ""
    account_number: str = ""
    account_password: str = ""
    is_simulated: bool = True
    # REST API 기본 URL (키움 개발자 포털 참조)
    base_url: str = "https://openapi.kiwoom.com:9443"
    tr_delay_ms: int = 200


@dataclass
class OpenAIConfig:
    api_key: str = ""
    model: str = "gpt-4o"
    max_tokens: int = 1000
    temperature: float = 0.3
    timeout: int = 30


@dataclass
class GeminiConfig:
    api_key: str = ""
    model: str = "gemini-1.5-pro"
    max_tokens: int = 1000
    temperature: float = 0.3
    timeout: int = 30


@dataclass
class RiskConfig:
    max_positions: int = 5
    max_position_pct: float = 0.10
    max_total_exposure_pct: float = 0.50
    stop_loss_pct: float = 0.03
    take_profit_pct: float = 0.05
    min_confidence: float = 0.70
    max_daily_trades: int = 10


@dataclass
class SchedulerConfig:
    market_open: str = "09:05"
    market_close: str = "15:20"
    analysis_interval_min: int = 30
    pre_close_minutes: int = 30
    timezone: str = "Asia/Seoul"


@dataclass
class AppConfig:
    kiwoom: KiwoomConfig = field(default_factory=KiwoomConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    top_n_stocks: int = 20
    log_level: str = "INFO"
    log_dir: str = "logs"
    data_dir: str = "data"


def load_config(config_path: str = "config/config.yaml") -> AppConfig:
    load_dotenv()

    raw: dict = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    kiwoom_raw = raw.get("kiwoom", {})
    kiwoom_raw["app_key"]        = os.getenv("KIWOOM_APP_KEY",    kiwoom_raw.get("app_key", ""))
    kiwoom_raw["app_secret"]     = os.getenv("KIWOOM_APP_SECRET", kiwoom_raw.get("app_secret", ""))
    kiwoom_raw["account_number"] = os.getenv("KIWOOM_ACCOUNT",    kiwoom_raw.get("account_number", ""))
    kiwoom_raw["account_password"] = os.getenv("KIWOOM_ACCOUNT_PW", kiwoom_raw.get("account_password", ""))

    openai_raw = raw.get("openai", {})
    openai_raw["api_key"] = os.getenv("OPENAI_API_KEY", openai_raw.get("api_key", ""))

    gemini_raw = raw.get("gemini", {})
    gemini_raw["api_key"] = os.getenv("GEMINI_API_KEY", gemini_raw.get("api_key", ""))

    return AppConfig(
        kiwoom=KiwoomConfig(**kiwoom_raw),
        openai=OpenAIConfig(**openai_raw),
        gemini=GeminiConfig(**gemini_raw),
        risk=RiskConfig(**raw.get("risk", {})),
        scheduler=SchedulerConfig(**raw.get("scheduler", {})),
        top_n_stocks=raw.get("top_n_stocks", 20),
        log_level=raw.get("log_level", "INFO"),
        log_dir=raw.get("log_dir", "logs"),
        data_dir=raw.get("data_dir", "data"),
    )
