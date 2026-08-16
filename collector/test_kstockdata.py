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
