"""키움 주문 미러링 검증 — 네트워크 없이 페이로드·상한·선점·격리만 본다.

실행: uv run python test_kiwoom_order.py
"""

import sys
from datetime import datetime
from pathlib import Path

import kiwoom_order as ko

# --- 실전 호스트 유입 차단 ---------------------------------------------------
SRC = Path(ko.__file__).read_text(encoding="utf-8")
_stripped = SRC.replace("mockapi.kiwoom.com", "").replace("openapi.kiwoom.com", "")
assert "api.kiwoom.com" not in _stripped, "실전 호스트 문자열 발견"
assert ko.MOCK_HOST == "https://mockapi.kiwoom.com"

# --- TR 매핑 ----------------------------------------------------------------
assert ko.tr_for("BUY") == "kt10000"
assert ko.tr_for("SELL") == "kt10001"

# --- 페이로드 ---------------------------------------------------------------
assert ko.order_payload("BUY", "005930", 10, "MARKET", None, 70000) == {
    "dmst_stex_tp": "KRX",
    "stk_cd": "005930",
    "ord_qty": "10",
    "ord_uv": "",
    "trde_tp": "3",
}
assert ko.order_payload("SELL", "005930", 3, "LIMIT", 71000, 70000) == {
    "dmst_stex_tp": "KRX",
    "stk_cd": "005930",
    "ord_qty": "3",
    "ord_uv": "71000",
    "trde_tp": "0",
}

# --- 상한·형식 거부 ----------------------------------------------------------
def rejects(**kw) -> bool:
    args = {"side": "BUY", "ticker": "005930", "qty": 1, "order_type": "MARKET",
            "limit_price": None, "ref_price": 70000}
    args.update(kw)
    try:
        ko.order_payload(**args)
        return False
    except ko.LimitError:
        return True


assert rejects(qty=0), "수량 0 통과"
assert rejects(qty=ko.MAX_QTY + 1), "수량 상한 통과"
assert rejects(qty=1000, ref_price=70000), "금액 상한 통과"  # 7천만원
assert rejects(ticker="00593"), "종목코드 길이 통과"
assert rejects(ticker="A05930"), "비숫자 종목코드 통과"
assert rejects(side="SHORT"), "매매구분 오류 통과"
assert rejects(order_type="LIMIT", limit_price=None), "지정가 없는 LIMIT 통과"
assert rejects(ref_price=0), "기준가 0 통과"

# --- --since 검증 ------------------------------------------------------------
NOW = datetime(2026, 8, 3, 10, 0, tzinfo=ko.KST)


def since_rejects(s: str) -> bool:
    try:
        ko.valid_since(s, NOW)
        return False
    except ko.LimitError:
        return True


assert ko.valid_since("2026-08-01", NOW) == "2026-08-01"
assert since_rejects("2026-8-1"), "형식 위반 통과"
assert since_rejects("2026-08-03; DROP TABLE orders"), "주입 문자열 통과"
assert since_rejects("2026-08-04"), "미래 날짜 통과"
assert since_rejects("2020-01-01"), "과거 상한 통과"

# --- 미러링 ------------------------------------------------------------------
ROWS = [
    {"id": 11, "ticker": "005930", "side": "BUY", "order_type": "MARKET", "qty": 10,
     "limit_price": None, "ordered_at": "2026-08-03 09:31", "fill_price": 70100},
    {"id": 12, "ticker": "000660", "side": "SELL", "order_type": "LIMIT", "qty": 2,
     "limit_price": 265000, "ordered_at": "2026-08-03 10:02", "fill_price": 265000},
]


class FakeDb:
    """query()는 SELECT면 ROWS, 선점 UPDATE면 claim_ok에 따라 RETURNING 결과를 흉내낸다."""

    def __init__(self, rows=None, claim_ok=True):
        self.rows = ROWS if rows is None else rows
        self.claim_ok = claim_ok
        self.updates: list[tuple] = []
        self.selected: list[tuple] = []
        self.claims: list[tuple] = []

    def query(self, sql, args=()):
        if sql.strip().upper().startswith("SELECT"):
            assert "COALESCE(o.broker_order_id, '') = ''" in sql, "멱등 필터 없음"
            assert "o.owner_id = ?" in sql, "owner_id 필터 없음"
            self.selected.append(args)
            return self.rows
        assert "RETURNING id" in sql, "선점을 RETURNING 없이 했다"
        self.claims.append(args)
        return [{"id": args[1]}] if self.claim_ok else []

    def execute(self, sql, args=()):
        self.updates.append((sql, args))


class FakeClient:
    def __init__(self, fail_on=(), token_fails=False):
        self.sent: list[tuple] = []
        self.fail_on = fail_on
        self.token_fails = token_fails
        self.token_calls = 0

    def token(self):
        self.token_calls += 1
        if self.token_fails:
            raise RuntimeError("인증 실패")
        return "FAKE_TOKEN"

    def place(self, side, payload):
        self.sent.append((side, payload))
        if payload["stk_cd"] in self.fail_on:
            raise RuntimeError("timeout")
        return f"ORD{len(self.sent):04d}"


# 드라이런은 DB를 건드리지 않는다
db = FakeDb()
assert ko.mirror(db, None, "2026-08-03", 20, 1) == 0
assert db.updates == [] and db.claims == [], "드라이런인데 DB를 건드렸다"
assert db.selected[0] == (1, "2026-08-03", 20), "owner_id/since/limit 바인딩 오류"

# 정상 경로: 전송 전 선점 → 전송 → 실제 주문번호로 덮어쓰기
db, client = FakeDb(), FakeClient()
assert ko.mirror(db, client, "2026-08-03", 20, 1) == 2
assert [s[0] for s in client.sent] == ["BUY", "SELL"]
assert client.sent[1][1]["ord_uv"] == "265000"
assert [c[1] for c in db.claims] == [11, 12], "선점 누락"
assert len(db.updates) == 2
assert db.updates[0][1][0] == "ORD0001" and db.updates[0][1][1] == 11
assert db.updates[0][1][2].startswith("SENDING:"), "선점 표식 조건 없이 덮어썼다"

# 선점 실패(다른 런이 이미 쥠) → 전송하지 않는다
db, client = FakeDb(claim_ok=False), FakeClient()
assert ko.mirror(db, client, "2026-08-03", 20, 1) == 0
assert client.sent == [], "선점 실패인데 전송했다"
assert db.updates == [], "선점 실패인데 기록했다"

# 전송 실패 → FAILED 마킹, 자동 재전송 없음, 다음 행은 계속 처리
db, client = FakeDb(), FakeClient(fail_on=("005930",))
assert ko.mirror(db, client, "2026-08-03", 20, 1) == 1
assert db.updates[0][1][0].startswith("FAILED:"), "실패를 기록하지 않았다"
assert db.updates[0][1][1] == 11
assert len(client.sent) == 2, "실패 후 다음 주문이 막혔다"

# LimitError 격리: 상한 위반 1건이 뒤 주문을 막지 않는다
BAD = [dict(ROWS[0], id=13, qty=ko.MAX_QTY + 1), ROWS[1]]
db, client = FakeDb(rows=BAD), FakeClient()
assert ko.mirror(db, client, "2026-08-03", 20, 1) == 1, "LimitError가 미러링을 중단시켰다"
assert db.updates[0][1][0].startswith("SKIP:"), "위반 행을 마킹하지 않았다"
assert db.updates[0][1][1] == 13
assert [c[1] for c in db.claims] == [12], "위반 행을 선점했다"

# --- PENDING 주문(체결가 없음)은 시장 종가를 기준가로 미러링 ---
# 키움은 장중에만 주문을 받으므로 방금 낸(아직 미체결) 주문을 그 즉시 보낸다.
class FakeMarketDb:
    def query(self, sql, args=()):
        assert "daily_prices" in sql
        return [{"close": 70000}]


PENDING = [dict(ROWS[0], id=21, fill_price=None)]  # 아직 체결 전
db, client = FakeDb(rows=PENDING), FakeClient()
assert ko.mirror(db, client, "2026-08-03", 20, 1, FakeMarketDb()) == 1, "PENDING을 못 보냈다"
assert client.sent[0][1]["stk_cd"] == "005930"
# 기준가를 못 구하면(market_db 없음) 금액 상한을 검증할 수 없어 그 건만 SKIP
db, client = FakeDb(rows=PENDING), FakeClient()
assert ko.mirror(db, client, "2026-08-03", 20, 1, None) == 0
assert client.sent == [] and db.updates[0][1][0].startswith("SKIP:"), "기준가 없으면 SKIP해야"

# --- main(): --account-id 필수 + --limit 하한 --------------------------------
MAIN_DB = FakeDb(rows=[])
ko.Turso.from_env = staticmethod(lambda db: MAIN_DB)  # type: ignore[method-assign]


def run_main(*argv) -> int:
    sys.argv = ["kiwoom_order.py", *argv]
    return ko.main()


assert run_main() == 2, "--account-id 없이 통과"
assert run_main("--account-id", "0") == 2, "--account-id 0 통과"
assert run_main("--account-id", "1", "--limit", "-1") == 0
assert MAIN_DB.selected[-1][2] == 1, f"--limit -1이 무제한으로 샜다: {MAIN_DB.selected[-1]}"
assert run_main("--account-id", "1", "--limit", "999") == 0
assert MAIN_DB.selected[-1][2] == ko.MAX_ORDERS_PER_RUN, "런당 상한 초과"
assert run_main("--account-id", "1", "--since", "2020-01-01") == 2, "과거 --since 통과"

print("kiwoom_order 검증 통과")

# 드라이런 출력 예시 — 어떤 주문이 어떤 페이로드로 나가는지
print("\n--- dry-run 예시 ---")
ko.mirror(FakeDb(), None, "2026-08-03", 20, 1)

# --- 토큰 선발급: 인증 실패가 대상 행을 FAILED로 태우지 않아야 한다 ---
# 지연 발급이면 건별 예외로 잡혀 최대 20건이 영구 배제된다(다시 조회되지 않음).
db = FakeDb()
client = FakeClient(token_fails=True)
try:
    ko.mirror(db, client, "2026-08-03", 20, 1)
    raise AssertionError("인증 실패인데 예외가 안 났다")
except RuntimeError as e:
    assert "인증" in str(e), e
assert client.sent == [], "인증 실패인데 주문이 전송됐다"
assert db.claims == [], "인증 실패인데 행을 선점했다"
assert not any("FAILED" in str(a) for _, a in db.updates), \
    f"인증 실패로 행이 FAILED 마킹됨 — 다음 런에서 영구 배제된다: {db.updates}"
assert client.token_calls == 1, "토큰을 루프 전에 한 번 받아야 한다"
print("토큰 선발급 회귀 테스트 OK")

# --- 키움 → 웹 동기화 (키움이 기준) ---
POS_JSON = {"acnt_evlt_remn_indv_tot": [
    {"stk_cd": "005930", "rmnd_qty": "000000000003", "pur_pric": "000000240000"},
    {"stk_cd": "A000660", "rmnd_qty": "2", "pur_pric": "1,718,000"},  # A 접두사·콤마
    {"stk_cd": "005930", "rmnd_qty": "0", "pur_pric": "0"},           # 수량 0 → 버림
]}
pos = ko.parse_positions(POS_JSON)
assert pos == [
    {"ticker": "005930", "qty": 3, "avg_price": 240000},
    {"ticker": "000660", "qty": 2, "avg_price": 1718000},
], pos
assert ko.parse_positions({}) == [] and ko.parse_positions({"acnt_evlt_remn_indv_tot": None}) == []
assert ko._num("000000010000000") == 10000000 and ko._num("-1,234") == 1234 and ko._num("") == 0


class SyncClient:
    def deposit(self):
        return {"entr": "000000009500000"}  # 예수금 950만

    def balance(self):
        return POS_JSON


class SyncDb:
    def __init__(self, orders):
        self.orders = orders
        self.batch = None

    def query(self, sql, args=()):
        assert "status = 'PENDING'" in sql
        return self.orders

    def execute_batch(self, stmts):
        self.batch = stmts


ORDERS = [
    {"id": 5, "ticker": "005930", "qty": 3, "broker_order_id": "0001234"},   # 키움 접수 → FILLED
    {"id": 6, "ticker": "999999", "qty": 1, "broker_order_id": "FAILED:x"},  # 미전송 → REJECTED
    {"id": 7, "ticker": "000660", "qty": 2, "broker_order_id": ""},          # 미전송 → PENDING 유지
]
sdb = SyncDb(ORDERS)
ko.sync_from_kiwoom(sdb, SyncClient(), 1, "2026-08-05")
sqls = [s[0] for s in sdb.batch]
assert sdb.batch[0] == ("UPDATE accounts SET cash = ? WHERE id = ?", (9500000, 1)), "예수금 반영"
assert any("DELETE FROM positions" in s for s in sqls)
assert sum(1 for s in sqls if "INSERT INTO positions" in s) == 2, "보유 2종목 반영"
assert any("status = 'FILLED'" in s for s in sqls), "키움 접수분 FILLED"
assert any("status = 'REJECTED'" in s for s in sqls), "미전송분 REJECTED"
assert not any("id = ? AND status = 'PENDING'" in s and s[1] == (7,) for s in sdb.batch), "미전송(빈) 주문은 손대지 않음"
print("키움→웹 동기화 테스트 OK")
