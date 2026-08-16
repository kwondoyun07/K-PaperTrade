"""측정 신뢰성 검증 — 네트워크 없이 (FDR 실측 응답 형식 축약).

- 지수 파싱·upsert(결손 시 실패)
- AI 판단 수익률 기준가(decision_price vs 판단일 종가 폴백)
- track_record가 폴백 기준가 행을 프롬프트에 먹이지 않는지

실행: uv run python test_indices.py
"""

import numpy as np
import pandas as pd

from daily import INDEX_UPSERT, index_rows, upsert_indices

# FDR DataReader("KS11", ...) 실측 컬럼 (2026-08-16 확인)
COLS = ["Close", "UpDown", "Comp", "Change", "Open", "High", "Low", "Volume", "Amount", "MarCap"]


def frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows).set_index("Date")
    df.index = pd.to_datetime(df.index)
    return df.reindex(columns=COLS)


DF = frame([
    {"Date": "2026-08-13", "Open": 6814.0, "High": 6900.1, "Low": 6800.2, "Close": 6813.34, "Volume": 512345678},
    # 시/고/저 0인 과거 행 → 종가로 대체하고 행은 살린다
    {"Date": "2026-08-14", "Open": 0.0, "High": 0.0, "Low": 0.0, "Close": 6977.94, "Volume": 401234567},
    # 거래량 결측 → 0
    {"Date": "2026-08-17", "Open": 7000.0, "High": 7010.0, "Low": 6990.0, "Close": 7001.0, "Volume": np.nan},
    # 시/고/저 NaN → 종가로 대체. `float(x) or close`는 bool(nan)=True라 NaN을 통과시켰고
    # indices는 NOT NULL 스키마다
    {"Date": "2026-08-20", "Open": np.nan, "High": np.nan, "Low": np.nan, "Close": 7100.0, "Volume": 3},
    # 종가 결측/0 → 벤치마크로 못 쓰므로 버린다
    {"Date": "2026-08-18", "Open": 7000.0, "High": 7010.0, "Low": 6990.0, "Close": np.nan, "Volume": 1},
    {"Date": "2026-08-19", "Open": 7000.0, "High": 7010.0, "Low": 6990.0, "Close": 0.0, "Volume": 1},
])

rows = index_rows(DF, "KOSPI")
assert len(rows) == 4, f"기대 4행, 실제 {len(rows)} — 종가 결측/0 행이 안 걸러졌다"
assert rows[0] == ("KOSPI", "2026-08-13", 6814.0, 6900.1, 6800.2, 6813.34, 512345678), rows[0]
assert rows[1] == ("KOSPI", "2026-08-14", 6977.94, 6977.94, 6977.94, 6977.94, 401234567), rows[1]
assert rows[2][6] == 0 and isinstance(rows[2][6], int), "거래량 결측은 0(int)이어야"
assert rows[3] == ("KOSPI", "2026-08-20", 7100.0, 7100.0, 7100.0, 7100.0, 3), rows[3]
assert not any(x != x for r in rows for x in r[2:6]), f"NaN이 그대로 통과했다: {rows}"
assert all(isinstance(x, float) for x in rows[0][2:6]), "OHLC는 float (지수는 소수점 포인트)"
assert index_rows(DF.iloc[:0], "KOSPI") == [], "빈 프레임 → 빈 리스트"


# --- upsert_indices: 스텁 DB/FDR로 SQL·실패처리 검증 ---
class FakeDB:
    def __init__(self):
        self.stmts = []

    def execute_batch(self, stmts, chunk=200):
        self.stmts += stmts


import daily  # noqa: E402

_real = daily.fdr.DataReader
try:
    daily.fdr.DataReader = lambda code, s, e: DF  # 두 지수 모두 같은 픽스처
    db = FakeDB()
    n = upsert_indices(db, "2026-08-13", "2026-08-19")
    assert n == 8, f"KOSPI 4 + KOSDAQ 4 = 8행 기대, 실제 {n}"
    assert {s[1][0] for s in db.stmts} == {"KOSPI", "KOSDAQ"}, "code는 KOSPI/KOSDAQ (KS11 아님 — 웹 조회 키)"
    assert all(s[0] is INDEX_UPSERT for s in db.stmts)
    assert all(len(s[1]) == 7 for s in db.stmts), "바인딩 인자 7개(code,date,o,h,l,c,v)"

    # 조회 자체가 터져도 조용히 넘어가면 안 된다 — 벤치마크 필수 데이터
    def boom(code, s, e):
        raise RuntimeError("upstream 500")

    daily.fdr.DataReader = boom
    db2 = FakeDB()
    try:
        upsert_indices(db2, "2026-08-13")
        raise AssertionError("전부 실패인데 예외가 안 났다")
    except RuntimeError as e:
        assert "0행" in str(e) and "upstream 500" in str(e), e
    assert db2.stmts == [], "실패 시 쓰기 없음"

    # 한쪽만 실패해도 실패다 — KOSPI만 들어오고 KOSDAQ이 비면 코스닥 종목의 벤치마크가
    # 통째로 없는데 예전엔 stmts가 비지 않는다고 rc=0으로 조용히 넘어갔다(CI 초록)
    daily.fdr.DataReader = lambda code, s, e: DF if code == "KS11" else DF.iloc[:0]
    db3 = FakeDB()
    try:
        upsert_indices(db3, "2026-08-13", "2026-08-19")
        raise AssertionError("KOSDAQ 결손인데 예외가 안 났다 — 조용히 초록이 된다")
    except RuntimeError as e:
        assert "KOSDAQ" in str(e) and "일부 결손" in str(e), e
    assert len(db3.stmts) == 4 and {s[1][0] for s in db3.stmts} == {"KOSPI"}, "받아온 쪽은 그대로 쓴다"
finally:
    daily.fdr.DataReader = _real


# --- update_ai_returns: 기준가 (B-1) ---
class RetDB:
    """ai_decisions(trading) / daily_prices(krx_market) 겸용 스텁."""

    def __init__(self, rows: list[dict] | None = None, closes: list[dict] | None = None):
        self.rows, self.closes, self.updates = rows or [], closes or [], []

    def query(self, sql, args=()):
        return self.closes if "daily_prices" in sql else self.rows

    def execute(self, sql, args=()):
        self.updates.append((sql, args))


CLOSES = [{"date": f"2026-08-{d:02d}", "close": c} for d, c in
          ((3, 1000), (4, 1100), (5, 1050), (6, 1080), (7, 1090), (10, 1200))]  # +5거래일 = 1200


def _ret(decision_price):
    tdb = RetDB([{"id": 7, "ticker": "005930", "ts": "2026-08-03 12:30",
                  "decision_price": decision_price, "ret_d5": None, "ret_d20": None, "ret_d60": None}])
    daily.update_ai_returns(tdb, RetDB(closes=CLOSES))
    assert len(tdb.updates) == 1, tdb.updates
    sql, args = tdb.updates[0]
    return sql, dict(zip([s.split(" =")[0] for s in sql.split("SET ")[1].split(" WHERE")[0].split(", ")], args))


# 판단 시점가(980)가 기준 — 판단일 종가(1000)와 다른 값이 나와야 BUY/HOLD가 구분된다
sql, got = _ret(980.0)
assert got["ret_basis"] == "decision", got
assert abs(got["ret_d5"] - (1200 / 980 - 1) * 100) < 1e-9, got
# 기준가가 없는 과거분 → 판단일 종가 폴백. 신뢰할 수 없음을 ret_basis로 구분한다
sql, got = _ret(None)
assert got["ret_basis"] == "close", got
assert abs(got["ret_d5"] - (1200 / 1000 - 1) * 100) < 1e-9, got


# --- track_record: 폴백 기준가 행은 프롬프트에 안 먹인다 (B-1) ---
import decide  # noqa: E402

_get = decide.api_get
try:
    DECS = [
        {"action": "BUY", "ret_d5": -5.0, "ret_basis": None},    # 컬럼 도입 전 계산분
        {"action": "BUY", "ret_d5": -9.0, "ret_basis": "close"},  # decision_price 없는 폴백
        {"action": "BUY", "ret_d5": 3.0, "ret_basis": "decision"},
        {"action": "HOLD", "ret_d5": 1.0, "ret_basis": "decision"},
    ]
    decide.api_get = lambda path: {"decisions": DECS}
    s = decide.track_record()
    assert "BUY 1건" in s and "+3.00%" in s, s  # 폴백 2건은 평균에서 빠진다
    assert "HOLD 1건" in s, s

    decide.api_get = lambda path: {"decisions": DECS[:2]}
    assert decide.track_record() == "", "신뢰 가능한 행이 없으면 빈 문자열(틀린 신호보다 없는 신호)"
finally:
    decide.api_get = _get


print("test_indices OK")
