"""decide.py 검증 — LLM 출력 파서·스키마 검증·주문 상한·멱등성.

돈이 나가는 경로라 여기가 뚫리면 곧바로 잘못된 주문이 된다.
실행: uv run python test_decide.py
"""

from datetime import datetime

from decide import ApiError, api_get, market_open, order_block_reason, parse_decisions, plan_orders, validate

UNIVERSE = ["005930", "000660", "207940"]
FEATS = {"005930": {"close": 70_000}, "000660": {"close": 200_000}, "207940": {"close": 1_000_000}}
EMPTY = {"cash": 0, "equity": 0, "positions": []}


def d(ticker, action, reason="r"):
    return {"ticker": ticker, "action": action, "reason": reason}


# --- 파서: 코드펜스·잡담·깨진 JSON ---
assert parse_decisions('[{"ticker":"005930","action":"BUY","reason":"x"}]') == [
    {"ticker": "005930", "action": "BUY", "reason": "x"}
]
assert parse_decisions('```json\n[{"ticker":"005930","action":"HOLD"}]\n```')[0]["action"] == "HOLD"
assert parse_decisions('설명입니다.\n[{"ticker":"005930","action":"SELL"}]\n끝.')[0]["action"] == "SELL"
assert parse_decisions("판단 불가") == []
assert parse_decisions('[{"ticker": broken}]') == []
assert parse_decisions('{"ticker":"005930"}') == [], "배열이 아니면 버려야 한다"
assert parse_decisions(None) == []

# --- 스키마 검증: 유니버스 밖·알 수 없는 action·중복·비-dict ---
raw = [
    {"ticker": "005930", "action": "buy", "reason": "소문자 action 허용"},
    {"ticker": "999999", "action": "BUY"},          # 유니버스 밖
    {"ticker": "000660", "action": "MOON"},          # 알 수 없는 action
    {"ticker": "005930", "action": "SELL"},          # 중복 → 첫 판단만
    "쓰레기",                                          # 비-dict
    {"ticker": 207940, "action": "HOLD", "reason": "x" * 500},  # int 코드·긴 근거
]
v = validate(raw, UNIVERSE)
assert [x["ticker"] for x in v] == ["005930", "207940"], v
assert v[0]["action"] == "BUY"
assert len(v[1]["reason"]) == 200, "근거는 200자로 잘린다"
assert validate([{"ticker": "5930", "action": "BUY"}], UNIVERSE)[0]["ticker"] == "005930", "6자리 제로패딩"

# --- 매수: 주문금액 상한 (체결가 +30% 버퍼) ---
pf = {"cash": 100_000_000, "equity": 100_000_000, "positions": []}
o, _ = plan_orders([d("005930", "BUY")], FEATS, pf, set(), "2026-08-03",
                   max_krw=1_000_000, max_qty=100, max_pos_pct=100, max_orders=5)
assert o[0]["qty"] == 10, o  # 1,000,000 // (70,000*1.3=91,000)
# MARKET은 다음 분봉에서 체결된다. 상한가로 체결돼도 금액 상한을 넘으면 안 된다.
assert o[0]["qty"] * 70_000 * 1.3 <= 1_000_000, "상한가 체결 시 금액 상한 초과"
assert (o[0]["qty"] + 1) * 70_000 * 1.3 > 1_000_000, "버퍼가 필요 이상으로 보수적"

# --- 매수: 수량 상한이 금액 상한보다 먼저 걸리는 경우 ---
o, _ = plan_orders([d("005930", "BUY")], FEATS, pf, set(), "2026-08-03",
                   max_krw=1_000_000, max_qty=5, max_pos_pct=100, max_orders=5)
assert o[0]["qty"] == 5, o

# --- 매수: 종목당 최대 비중 ---
pf2 = {"cash": 100_000_000, "equity": 10_000_000,
       "positions": [{"ticker": "005930", "qty": 20, "value": 1_400_000}]}
o, s = plan_orders([d("005930", "BUY")], FEATS, pf2, set(), "2026-08-03",
                   max_krw=100_000_000, max_qty=1000, max_pos_pct=20, max_orders=5)
assert o[0]["qty"] == 6, o  # 10,000,000*20% - 1,400,000 = 600,000 → 600,000//91,000 = 6주
o, s = plan_orders([d("005930", "BUY")], FEATS, pf2, set(), "2026-08-03",
                   max_krw=100_000_000, max_qty=1000, max_pos_pct=10, max_orders=5)
assert not o and "비중" in s[0][1], s  # 이미 비중 초과 → 매수 없음

# --- 매수: 현금 부족 ---
o, s = plan_orders([d("005930", "BUY")], FEATS, {"cash": 10_000, "equity": 10_000, "positions": []},
                   set(), "2026-08-03", max_krw=1_000_000, max_qty=100, max_pos_pct=100, max_orders=5)
assert not o and "여력" in s[0][1], s

# --- 매수: 배치 안에서 현금이 이중 사용되지 않는다 ---
pf3 = {"cash": 1_500_000, "equity": 10_000_000, "positions": []}
o, _ = plan_orders([d("005930", "BUY"), d("000660", "BUY")], FEATS, pf3, set(), "2026-08-03",
                   max_krw=1_000_000, max_qty=1000, max_pos_pct=100, max_orders=5)
assert o[0]["qty"] == 10 and o[1]["qty"] == 2, o  # 잔여 590,000 // 260,000 = 2

# --- 매도: 보유 수량을 넘지 않는다 / 미보유는 거부 ---
pf4 = {"cash": 0, "equity": 700_000, "positions": [{"ticker": "005930", "qty": 3, "value": 210_000}]}
o, _ = plan_orders([d("005930", "SELL")], FEATS, pf4, set(), "2026-08-03",
                   max_krw=1_000_000, max_qty=100, max_pos_pct=20, max_orders=5)
assert o[0]["qty"] == 3, o
o, s = plan_orders([d("000660", "SELL")], FEATS, pf4, set(), "2026-08-03",
                   max_krw=1_000_000, max_qty=100, max_pos_pct=20, max_orders=5)
assert not o and s[0][1] == "미보유", s

# --- 일일 주문 건수 상한 (이미 낸 주문 포함) ---
o, s = plan_orders([d("005930", "BUY"), d("000660", "BUY")], FEATS, pf, set(), "2026-08-03",
                   placed_today=1, max_krw=1_000_000, max_qty=100, max_pos_pct=100, max_orders=2)
assert len(o) == 1 and "일일 주문 상한" in s[0][1], (o, s)
o, s = plan_orders([d("005930", "BUY")], FEATS, pf, set(), "2026-08-03",
                   placed_today=5, max_krw=1_000_000, max_qty=100, max_pos_pct=100, max_orders=5)
assert not o, "상한 소진 상태에서는 한 건도 나가면 안 된다"

# --- 멱등성: 같은 날 **같은 방향** 주문은 다시 나가지 않는다 ---
LIM = {"max_krw": 1_000_000, "max_qty": 100, "max_pos_pct": 100, "max_orders": 5}
done = {("005930", "2026-08-03", "BUY")}
o, s = plan_orders([d("005930", "BUY")], FEATS, pf, done, "2026-08-03", **LIM)
assert not o and s[0][1] == "당일 매수 중복", s
o, _ = plan_orders([d("005930", "BUY")], FEATS, pf, done, "2026-08-04", **LIM)
assert o, "다음 거래일에는 다시 주문할 수 있어야 한다"

# 오전에 산 종목을 그날 팔 수 있어야 한다. SELL이 유일한 손절 경로라 이게 막히면
# 산 날 악재가 나도 못 판다 — 8/26에 11:49 매수한 005935의 13:10 SELL이 실제로 막혔다.
o, s = plan_orders([d("005930", "SELL")], FEATS, pf4, done, "2026-08-03", **LIM)
assert o and o[0]["side"] == "SELL", (o, s)

# 반대로 매도가 나간 뒤 같은 날 또 매도하지는 않는다(왕복은 1회까지).
done2 = {("005930", "2026-08-03", "SELL")}
o, s = plan_orders([d("005930", "SELL")], FEATS, pf4, done2, "2026-08-03", **LIM)
assert not o and s[0][1] == "당일 매도 중복", s

# --- 매도는 보유 전량이 나간다: 금액 상한은 매수 논리라 손절을 부분매도로 끝낸다 ---
# 실측 매도 12건 중 9건이 AI가 정한 수량이 아니라 100만원 상한이 허용한 수량이었다.
big = {"cash": 0, "equity": 100_000_000, "positions": [{"ticker": "005930", "qty": 5, "value": 5_000_000}]}
o, _ = plan_orders([d("005930", "SELL")], {"005930": {"close": 1_000_000}}, big, set(), "2026-08-03",
                   max_krw=1_000_000, max_qty=100, max_pos_pct=100, max_orders=5)
assert o[0]["qty"] == 5, f"보유 5주 전량이 나가야 한다 (금액 상한 100만원 × 주당 100만원): {o}"

# 수량 상한은 매도에도 그대로 걸린다(폭주 방지)
o, _ = plan_orders([d("005930", "SELL")], FEATS, {"cash": 0, "equity": 10_000_000,
                   "positions": [{"ticker": "005930", "qty": 500, "value": 5_000_000}]}, set(), "2026-08-03",
                   max_krw=1_000_000, max_qty=100, max_pos_pct=100, max_orders=5)
assert o[0]["qty"] == 100, o

# 매수는 여전히 상한가 버퍼로 보수적으로 잡는다(체결이 위로 튀어도 현금을 안 넘게)
o, _ = plan_orders([d("005930", "BUY")], {"005930": {"close": 100_000}},
                   {"cash": 1_000_000, "equity": 10_000_000, "positions": []}, set(), "2026-08-03",
                   max_krw=1_000_000, max_qty=100, max_pos_pct=100, max_orders=5)
assert o[0]["qty"] == 7, f"1,000,000 // (100,000×1.3) = 7주여야 한다: {o}"

# --- HOLD은 주문도 스킵 사유도 만들지 않는다 / 가격 없는 종목 거부 ---
o, s = plan_orders([d("005930", "HOLD")], FEATS, pf, set(), "2026-08-03")
assert not o and not s
o, s = plan_orders([d("005930", "BUY")], {"005930": {"close": 0}}, pf, set(), "2026-08-03")
assert not o and s[0][1] == "가격 없음", s
# 시세를 못 받은 종목(휴장·미거래)은 feats에 없어 주문되지 않는다
o, s = plan_orders([d("005930", "BUY")], {}, pf, set(), "2026-08-03")
assert not o and s[0][1] == "가격 없음", s


# --- 장중 판정 (평일 09:00~15:30 KST) ---
def dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


assert market_open(dt("2026-08-03 09:00"))   # 월요일 개장
assert market_open(dt("2026-08-03 15:29"))   # 15:30 봉으로 체결 가능
assert not market_open(dt("2026-08-03 08:59"))
assert not market_open(dt("2026-08-03 15:30")), "마지막 봉에 낸 주문은 체결될 다음 봉이 없다"
assert not market_open(dt("2026-08-03 18:30"))  # 기존 cron 시각 — 체결될 분봉이 없다
assert not market_open(dt("2026-08-01 10:00"))  # 토요일
assert not market_open(dt("2026-08-02 10:00"))  # 일요일

# --- 주문 경로 차단: 마감 후 / 과거 date / 계좌 미지정 ---
NOON = dt("2026-08-03 12:00")
assert order_block_reason("2026-08-03", NOON, 1) is None, "장중·오늘·계좌 있으면 통과"

def blocked(date, now, account, needle):
    why = order_block_reason(date, now, account)
    assert why and needle in why, f"차단돼야 한다: {date} {now} acct={account} → {why}"


# 1) 마감 후 주문은 ordered_at 이후 당일 분봉이 없어 영구 PENDING이 된다
blocked("2026-08-03", dt("2026-08-03 18:30"), 1, "장중 아님")  # 옛 cron 시각
blocked("2026-08-01", dt("2026-08-01 12:00"), 1, "장중 아님")  # 토요일

# 2) --date로 멱등 키·일일 상한 동시 우회 — date가 오늘이 아니면 주문 경로 자체를 막는다
blocked("2026-07-31", NOON, 1, "지표 기준일")
blocked("2026-08-04", NOON, 1, "지표 기준일")  # 미래 date도 동일

# 3) 계좌 미지정이면 사람 계좌로 새지 않게 주문 생략 (자동 선택 없음)
blocked("2026-08-03", NOON, 0, "AI_ACCOUNT_ID 미설정")
blocked("2026-08-03", NOON, None, "AI_ACCOUNT_ID 미설정")

# --- 기록 실패한 종목은 주문 후보에서 빠진다 ---
import decide  # noqa: E402  (아래 monkeypatch 전용)

calls = []


def fake_post(path, body, dry):
    calls.append(body["ticker"])
    return None if body["ticker"] == "000660" else {"id": len(calls)}


orig_post, decide.api_post = decide.api_post, fake_post
try:
    rec = decide.record_decisions([d("005930", "BUY"), d("000660", "BUY"), d("207940", "HOLD")],
                                  "2026-08-03 12:00", dry=False)
finally:
    decide.api_post = orig_post
assert calls == ["005930", "000660", "207940"], calls
assert [x["ticker"] for x in rec] == ["005930", "207940"], rec  # 기록 실패분 제외
o, _ = plan_orders(rec, FEATS, pf, set(), "2026-08-03")
assert [x["ticker"] for x in o] == ["005930"], o  # 000660은 주문되지 않는다

# --- GET 실패는 기본값이 아니라 중단 (fail-closed) ---
orig_api, decide.API = decide.API, "http://127.0.0.1:1/api/v1"
try:
    api_get("/orders?account_id=1")
    raise AssertionError("GET 실패인데 예외가 없다 — 상한·멱등 키가 빈 채로 주문이 나간다")
except ApiError as e:
    assert "GET /orders" in str(e), e
finally:
    decide.API = orig_api

# --- 진입 위치 규율: 매수만 조이고 손절은 그대로 둔다 ---
# 8/26·9/7 두 시점에서 독립적으로 관찰된 추격 매수를 프롬프트로 억제한다.
# 매도까지 조이면 손절이 둔해져 8/28 같은 급락에서 더 크게 물린다 — 그래서
# "매수에만 적용"이 규율의 핵심이고, 그 문장이 사라지면 안 된다.
from decide import build_prompt, format_row

_row = format_row(
    "005930", "삼성전자",
    {"close": 100000, "n": 60, "chg1": 1.0, "chg5": 2.0, "chg20": 3.0,
     "ma5_gap": 1.0, "ma20_gap": 2.0, "vol_ratio": 1.2},
    {"last": 101000, "day_open": 99000, "day_high": 102000, "day_low": 98000,
     "from_open_pct": 2.0, "range_pos": 75, "vwap_gap": 0.8, "mom30": 0.5,
     "late30_vol_pct": 12.0, "bars": 180},
)
assert "고저위치 75%" in _row, _row  # 규율이 참조하는 값이 실제로 프롬프트에 있어야 한다
assert "VWAP이격 +0.80%" in _row, _row

_p = build_prompt([_row], {"005930": 7})
assert "매수는 진입 위치를 가려라" in _p
assert "고저위치 70% 이상" in _p
assert "매수에만 적용한다" in _p, "손절 면제 조항이 빠지면 급락에서 못 판다"
assert "손절·악재 청산은 가격 위치와 무관하게 즉시" in _p
# 매도 규율은 그대로 살아 있어야 한다
assert "손실이 -7% 이상인데 반등 신호" in _p
print("진입 위치 규율 테스트 OK")


print("test_decide OK")
