import json
import logging
import time

from openai import AsyncOpenAI

from config.settings import OpenAIConfig
from src.ai.base_analyzer import Action, AnalysisResult, BaseAnalyzer
from src.ai.prompts import STOCK_ANALYSIS_SYSTEM, STOCK_ANALYSIS_USER_TEMPLATE

logger = logging.getLogger(__name__)


class GPTAnalyzer(BaseAnalyzer):
    def __init__(self, config: OpenAIConfig):
        self.config = config
        self.client = AsyncOpenAI(api_key=config.api_key, timeout=config.timeout)

    async def analyze(self, stock_data: "StockData") -> AnalysisResult:
        prompt = STOCK_ANALYSIS_USER_TEMPLATE.format(**stock_data.to_prompt_dict())
        t0 = time.monotonic()

        response = await self.client.chat.completions.create(
            model=self.config.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": STOCK_ANALYSIS_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
        )
        latency = (time.monotonic() - t0) * 1000

        raw = json.loads(response.choices[0].message.content)
        result = AnalysisResult(
            stock_code=stock_data.code,
            stock_name=stock_data.name,
            action=Action(raw["action"]),
            confidence=float(raw["confidence"]),
            target_price=int(raw["target_price"]),
            stop_loss_price=int(raw["stop_loss_price"]),
            holding_period_days=int(raw["holding_period_days"]),
            reasoning=raw.get("reasoning", ""),
            risk_factors=raw.get("risk_factors", []),
            bullish_signals=raw.get("bullish_signals", []),
            bearish_signals=raw.get("bearish_signals", []),
            model_name=self.config.model,
            latency_ms=latency,
        )
        logger.info(
            f"[GPT] {stock_data.name}: {result.action.value} "
            f"(신뢰도={result.confidence:.2f}, 응답시간={latency:.0f}ms)"
        )
        return result

    async def health_check(self) -> bool:
        try:
            await self.client.models.list()
            return True
        except Exception as e:
            logger.warning(f"GPT 헬스체크 실패: {e}")
            return False
