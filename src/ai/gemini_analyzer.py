import asyncio
import json
import logging
import time

import google.generativeai as genai

from config.settings import GeminiConfig
from src.ai.base_analyzer import Action, AnalysisResult, BaseAnalyzer
from src.ai.prompts import STOCK_ANALYSIS_SYSTEM, STOCK_ANALYSIS_USER_TEMPLATE

logger = logging.getLogger(__name__)


class GeminiAnalyzer(BaseAnalyzer):
    def __init__(self, config: GeminiConfig):
        self.config = config
        genai.configure(api_key=config.api_key)
        self._model = genai.GenerativeModel(
            model_name=config.model,
            system_instruction=STOCK_ANALYSIS_SYSTEM,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                max_output_tokens=config.max_tokens,
                temperature=config.temperature,
            ),
        )

    async def analyze(self, stock_data: "StockData") -> AnalysisResult:
        prompt = STOCK_ANALYSIS_USER_TEMPLATE.format(**stock_data.to_prompt_dict())
        t0 = time.monotonic()

        # google-generativeai SDK는 동기 방식이므로 스레드풀에서 실행
        response = await asyncio.to_thread(self._model.generate_content, prompt)
        latency = (time.monotonic() - t0) * 1000

        raw = json.loads(response.text)
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
            f"[Gemini] {stock_data.name}: {result.action.value} "
            f"(신뢰도={result.confidence:.2f}, 응답시간={latency:.0f}ms)"
        )
        return result

    async def health_check(self) -> bool:
        try:
            await asyncio.to_thread(genai.list_models)
            return True
        except Exception as e:
            logger.warning(f"Gemini 헬스체크 실패: {e}")
            return False
