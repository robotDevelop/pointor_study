import logging
from dataclasses import dataclass
from typing import Optional

from src.ai.base_analyzer import Action, AnalysisResult

logger = logging.getLogger(__name__)


@dataclass
class TradingDecision:
    stock_code: str
    stock_name: str
    final_action: Action
    combined_confidence: float
    gpt_result: Optional[AnalysisResult]
    gemini_result: Optional[AnalysisResult]
    consensus: bool
    target_price: int
    stop_loss_price: int
    reasoning_summary: str


class DecisionMaker:
    """
    GPT(55%)와 Gemini(45%) 추천을 가중 투표로 결합.

    - 두 모델 동의: confidence × 1.1 (합의 보너스)
    - 단일 모델만 가용: confidence × 0.7 (페널티)
    - 두 모델 반대 의견: HOLD (단, 한쪽이 0.85 초과 시 해당 방향 채택)
    - combined_confidence < min_confidence: HOLD 강제
    """

    GPT_WEIGHT          = 0.55
    GEMINI_WEIGHT       = 0.45
    AGREEMENT_BONUS     = 1.1
    SINGLE_PENALTY      = 0.7
    OVERRIDE_THRESHOLD  = 0.85
    BUY_THRESHOLD       = 0.3
    SELL_THRESHOLD      = -0.3

    def make_decision(
        self,
        gpt_result: Optional[AnalysisResult],
        gemini_result: Optional[AnalysisResult],
        min_confidence: float = 0.70,
    ) -> TradingDecision:
        gpt_ok    = gpt_result is not None
        gemini_ok = gemini_result is not None
        stock_code = (gpt_result or gemini_result).stock_code  # type: ignore[union-attr]
        stock_name = (gpt_result or gemini_result).stock_name  # type: ignore[union-attr]

        if not gpt_ok and not gemini_ok:
            return self._hold(stock_code, stock_name, None, None, "두 모델 모두 응답 실패")

        # 단일 모델 가용
        if not gpt_ok or not gemini_ok:
            result = gpt_result if gpt_ok else gemini_result
            assert result is not None
            confidence = result.confidence * self.SINGLE_PENALTY
            if confidence < min_confidence:
                return self._hold(stock_code, stock_name, gpt_result, gemini_result, "단일 모델 신뢰도 부족")
            return TradingDecision(
                stock_code=stock_code,
                stock_name=stock_name,
                final_action=result.action,
                combined_confidence=round(confidence, 4),
                gpt_result=gpt_result,
                gemini_result=gemini_result,
                consensus=False,
                target_price=result.target_price,
                stop_loss_price=result.stop_loss_price,
                reasoning_summary=f"[단일:{result.model_name}] {result.reasoning}",
            )

        # 두 모델 모두 가용
        assert gpt_result is not None and gemini_result is not None
        action, confidence = self._weighted_vote(gpt_result, gemini_result)
        consensus = gpt_result.action == gemini_result.action

        if consensus:
            confidence = min(confidence * self.AGREEMENT_BONUS, 1.0)

        if confidence < min_confidence:
            return self._hold(stock_code, stock_name, gpt_result, gemini_result, f"신뢰도 부족 ({confidence:.2f})")

        target, stop = self._combine_prices(gpt_result, gemini_result)
        summary = f"GPT:{gpt_result.action.value}({gpt_result.confidence:.2f}) Gemini:{gemini_result.action.value}({gemini_result.confidence:.2f})"

        return TradingDecision(
            stock_code=stock_code,
            stock_name=stock_name,
            final_action=action,
            combined_confidence=round(confidence, 4),
            gpt_result=gpt_result,
            gemini_result=gemini_result,
            consensus=consensus,
            target_price=target,
            stop_loss_price=stop,
            reasoning_summary=summary,
        )

    def _weighted_vote(
        self, gpt: AnalysisResult, gemini: AnalysisResult
    ) -> tuple:
        score = (
            self._action_to_score(gpt.action)    * gpt.confidence    * self.GPT_WEIGHT +
            self._action_to_score(gemini.action) * gemini.confidence * self.GEMINI_WEIGHT
        )
        # 두 모델이 반대 방향이면 HOLD (단, 한쪽이 오버라이드 임계값 초과 시 예외)
        if gpt.action != gemini.action:
            if gpt.confidence >= self.OVERRIDE_THRESHOLD:
                return gpt.action, gpt.confidence * self.SINGLE_PENALTY
            if gemini.confidence >= self.OVERRIDE_THRESHOLD:
                return gemini.action, gemini.confidence * self.SINGLE_PENALTY
            return Action.HOLD, 0.5

        action = self._score_to_action(score)
        confidence = (
            gpt.confidence * self.GPT_WEIGHT +
            gemini.confidence * self.GEMINI_WEIGHT
        )
        return action, confidence

    def _action_to_score(self, action: Action) -> float:
        return {Action.BUY: 1.0, Action.HOLD: 0.0, Action.SELL: -1.0}[action]

    def _score_to_action(self, score: float) -> Action:
        if score > self.BUY_THRESHOLD:
            return Action.BUY
        if score < self.SELL_THRESHOLD:
            return Action.SELL
        return Action.HOLD

    def _combine_prices(self, gpt: AnalysisResult, gemini: AnalysisResult) -> tuple:
        target = int(gpt.target_price * self.GPT_WEIGHT + gemini.target_price * self.GEMINI_WEIGHT)
        stop   = int(gpt.stop_loss_price * self.GPT_WEIGHT + gemini.stop_loss_price * self.GEMINI_WEIGHT)
        return target, stop

    def _hold(
        self,
        stock_code: str,
        stock_name: str,
        gpt: Optional[AnalysisResult],
        gemini: Optional[AnalysisResult],
        reason: str,
    ) -> TradingDecision:
        current = (gpt or gemini)
        target = current.target_price if current else 0
        stop   = current.stop_loss_price if current else 0
        logger.debug(f"[DecisionMaker] {stock_name} → HOLD: {reason}")
        return TradingDecision(
            stock_code=stock_code,
            stock_name=stock_name,
            final_action=Action.HOLD,
            combined_confidence=0.0,
            gpt_result=gpt,
            gemini_result=gemini,
            consensus=False,
            target_price=target,
            stop_loss_price=stop,
            reasoning_summary=f"HOLD: {reason}",
        )
