STOCK_ANALYSIS_SYSTEM = """
당신은 한국 주식 시장 전문 AI 투자 분석가입니다.
제공된 데이터를 바탕으로 냉정하고 객관적인 투자 분석을 수행합니다.
반드시 유효한 JSON 형식으로만 응답하십시오. 다른 텍스트를 포함하지 마십시오.
""".strip()

STOCK_ANALYSIS_USER_TEMPLATE = """
## 분석 대상 종목
- 종목코드: {stock_code}
- 종목명: {stock_name}
- 현재가: {current_price:,}원
- 시가총액: {market_cap}

## 기술적 지표
- RSI(14): {rsi:.1f}
- MACD: {macd:.2f} / Signal: {macd_signal:.2f}
- 볼린저밴드: 상단 {bb_upper:,} / 중단 {bb_middle:,} / 하단 {bb_lower:,}
- 5일 이동평균: {ma5:,}
- 20일 이동평균: {ma20:,}
- 60일 이동평균: {ma60:,}

## 거래량 분석
- 당일 거래량: {today_volume:,}
- 20일 평균 거래량: {avg_volume:,}
- 거래량 비율: {volume_ratio:.1f}%

## 재무 정보
- PER: {per}
- PBR: {pbr}
- EPS: {eps}원

## 최근 30일 OHLCV (최신 → 과거)
{ohlcv_table}

## 응답 형식 (JSON)
다음 JSON 형식으로만 응답하십시오:

{{
  "action": "BUY",
  "confidence": 0.75,
  "target_price": 80000,
  "stop_loss_price": 72000,
  "holding_period_days": 5,
  "reasoning": "분석 근거 200자 이내",
  "risk_factors": ["리스크1", "리스크2"],
  "bullish_signals": ["긍정신호1", "긍정신호2"],
  "bearish_signals": ["부정신호1"]
}}

action은 반드시 "BUY", "HOLD", "SELL" 중 하나여야 합니다.
confidence는 0.0에서 1.0 사이의 소수입니다.
""".strip()
