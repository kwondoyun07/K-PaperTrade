"""aikstockdata 파서 검증 — 파서는 네트워크 없이, 라이브 스모크는 --live로만.

실행: uv run python test_kstockdata.py [--live]
"""

import sys

import kstockdata as ks

# quotes.json 실제 응답 축약 — 정상 2건 + 거래정지(0) 1건
QUOTES = {
    "basDt": "20260813",
    "items": [
        {
            "basDt": "20260813", "종목코드": "000020", "종목명": "동화약품",
            "mrktCtg": "KOSPI", "clpr": 5140, "vs": -150, "fltRt": -2.84,
            "mkp": 5310, "hipr": 5310, "lopr": 5130, "trqu": 122645,
            "trPrc": 635783065, "lstgStCnt": 27931470, "mrktTotAmt": 143567755800,
        },
        {
            "basDt": "20260813", "종목코드": "005930", "종목명": "삼성전자",
            "mrktCtg": "KOSPI", "clpr": 268000, "vs": 12500, "fltRt": 4.89,
            "mkp": 267500, "hipr": 271000, "lopr": 262500, "trqu": 35530867,
            "trPrc": 9517753428321, "lstgStCnt": 5846278608, "mrktTotAmt": 1566802666944000,
        },
        {  # 거래정지 — 발행처가 0으로 채워 보낸다. 버려야 한다.
            "basDt": "20260813", "종목코드": "099999", "종목명": "정지종목",
            "mrktCtg": "KOSDAQ", "clpr": 1000, "vs": 0, "fltRt": 0.0,
            "mkp": 0, "hipr": 0, "lopr": 0, "trqu": 0,
            "trPrc": 0, "lstgStCnt": 1000000, "mrktTotAmt": 1000000000,
        },
    ],
}

rows = ks.parse_quotes(QUOTES)
assert len(rows) == 2, rows  # 거래정지 제외
assert rows[1] == {
    "ticker": "005930", "date": "2026-08-13", "open": 267500, "high": 271000,
    "low": 262500, "close": 268000, "volume": 35530867,
}, rows[1]
assert set(rows[0]) == {"ticker", "date", "open", "high", "low", "close", "volume"}

# history — [date, close, volume] 3열. OHLC가 없으므로 키도 없어야 한다.
HIST = {
    "code": "005930", "as_of": "20260813", "columns": ["date", "close", "volume"],
    "rows": [["20260811", 239500, 23310969], ["20260812", 255500, 27102479],
             ["20260813", 268000, 35530867]],
}
h = ks.parse_history(HIST)
assert h[0] == {"ticker": "005930", "date": "2026-08-11", "close": 239500,
                "volume": 23310969}, h[0]
assert "open" not in h[0], "history에는 시가가 없다 — 있는 척하면 daily_prices가 오염된다"
assert len(h) == 3

# disclosure_impact — enough=False는 버리고, CI가 0을 포함하면 significant=False
IMPACT = {
    "summary": [
        {"label": "잠정 실적(연결)", "h5": {"n": 184, "enough": True,
         "median_excess_pct": 1.15, "up_ratio_pct": 56.0, "ci_includes_zero": True}},
        {"label": "공급계약 체결", "h5": {"n": 219, "enough": True,
         "median_excess_pct": -0.46, "up_ratio_pct": 44.3, "ci_includes_zero": False}},
        {"label": "표본부족유형", "h5": {"n": 3, "enough": False,
         "median_excess_pct": 9.9, "up_ratio_pct": 99.0, "ci_includes_zero": True}},
        {"label": "h20미발행", "h5": None},
    ]
}
p = ks.parse_priors(IMPACT)
assert set(p) == {"잠정 실적(연결)", "공급계약 체결"}, p
assert p["잠정 실적(연결)"]["significant"] is False
assert p["공급계약 체결"]["significant"] is True
assert p["공급계약 체결"]["excess_pct"] == -0.46

print("파서 OK")

if "--live" in sys.argv:
    q = ks.quotes()
    print(f"live quotes: {len(q)}행, date={q[0]['date']}, 예: {q[0]}")
    hh = ks.history("005930")
    print(f"live history 005930: {len(hh)}행 {hh[0]['date']}~{hh[-1]['date']}")
    pp = ks.priors()
    sig = [k for k, v in pp.items() if v["significant"]]
    print(f"live priors: {len(pp)}유형, 유의(CI가 0 미포함): {sig or '없음'}")
    print("라이브 OK —", ks.CITATION)

# --- 액면분할 보정 (무보정 종가 → 소급 보정) ---
# 실측 근거: 010120이 2026-04-13에 5:1 분할. 원본 갭은 788,000 → 179,200(4.397배)로
# 정수 배수가 아니다(당일 주가 +13.7%가 섞임). 그래서 배수를 맞추려 하지 않고
# 관측 비율로 이어붙인다 — 구간 내 수익률은 전부 정확해지고 오차는 경계 하루로 갇힌다.
split = [
    {"date": "2026-04-08", "close": 800000, "volume": 100},
    {"date": "2026-04-10", "close": 788000, "volume": 120},
    {"date": "2026-04-13", "close": 179200, "volume": 600},  # 분할
    {"date": "2026-04-14", "close": 185000, "volume": 500},
]
adj = ks.adjust_splits(split)
assert adj[-1]["close"] == 185000 and adj[-2]["close"] == 179200, "최신 구간은 그대로여야"
r = 788000 / 179200
assert adj[0]["close"] == round(800000 / r) and adj[1]["close"] == round(788000 / r), adj
assert adj[1]["volume"] == round(120 * r), "거래량은 반대로 곱한다"
# 경계를 넘는 수익률이 ±30% 안으로 들어온다(원본은 -77%)
before = 179200 / 788000 - 1
after = adj[2]["close"] / adj[1]["close"] - 1
assert before < -0.7 and abs(after) < 0.01, f"경계 수익률 {before:.3f} → {after:.3f}"
# 구간 내 수익률은 보존된다
assert abs((adj[1]["close"] / adj[0]["close"]) - (788000 / 800000)) < 1e-6

# 정상 등락(가격제한 안)은 절대 건드리지 않는다 — 오탐 방지
normal = [
    {"date": "2026-04-08", "close": 100000, "volume": 10},
    {"date": "2026-04-10", "close": 71000, "volume": 20},   # -29%, 하한가 근처
    {"date": "2026-04-13", "close": 92000, "volume": 30},   # +29.6%
]
assert ks.adjust_splits(normal) == normal, "정상 등락을 분할로 오인했다"
assert ks.corporate_action_ratio(100000, 71000) is None
assert ks.corporate_action_ratio(788000, 179200) is not None
assert ks.adjust_splits([]) == [] and len(ks.adjust_splits(split[:1])) == 1

print("액면분할 보정 테스트 OK")
