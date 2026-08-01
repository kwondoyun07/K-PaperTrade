"""네이버 분봉 파서 검증 — 2026-08-01 실제 응답에서 채취한 축약 픽스처.

실행: uv run python test_parse.py
"""

from providers.naver import parse_minute

FIXTURE = [
    {"localDateTime": "20260731090200", "currentPrice": 248000.0, "openPrice": 257000.0,
     "highPrice": 260000.0, "lowPrice": 243500.0, "accumulatedTradingVolume": 4120623},
    {"localDateTime": "20260731090300", "currentPrice": 252000.0, "openPrice": 248000.0,
     "highPrice": 253500.0, "lowPrice": 246000.0, "accumulatedTradingVolume": 1181459},
    # O/H/L·거래량 결측 → close 대체, 거래량 0
    {"localDateTime": "20260731090400", "currentPrice": 250500.0, "openPrice": None,
     "highPrice": None, "lowPrice": None, "accumulatedTradingVolume": None},
    # 순서 뒤섞임 → 정렬 확인
    {"localDateTime": "20260731090100", "currentPrice": 246000.0, "openPrice": 246000.0,
     "highPrice": 246500.0, "lowPrice": 245500.0, "accumulatedTradingVolume": 100},
    # 불량 항목 → 스킵
    {"bogus": True},
    {"localDateTime": "20260731090500", "currentPrice": None},
]

bars = parse_minute("005930", FIXTURE)

assert len(bars) == 4, f"기대 4개, 실제 {len(bars)}"
assert [b.ts for b in bars] == [
    "2026-07-31 09:01", "2026-07-31 09:02", "2026-07-31 09:03", "2026-07-31 09:04",
], "시각 오름차순 정렬 실패"
b = bars[1]
assert (b.open, b.high, b.low, b.close, b.volume) == (257000, 260000, 243500, 248000, 4120623)
b = bars[3]  # 결측 항목
assert (b.open, b.high, b.low, b.close, b.volume) == (250500, 250500, 250500, 250500, 0)
assert all(isinstance(x, int) for x in (b.open, b.high, b.low, b.close, b.volume))

print("test_parse OK")
