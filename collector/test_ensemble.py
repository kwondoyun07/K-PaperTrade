"""ensemble.py 검증 — 합의·불일치·모델실패·전원실패. 네트워크 없이 돈다.

여기가 뚫리면 두 방향으로 돈이 샌다: 확신 없는데 매수(BUY 문턱이 낮을 때)와
팔아야 하는데 못 매도(SELL 문턱이 높을 때). 후자가 더 비싸다 — 이 시스템에
AI 판단 밖의 손절 경로가 없어서, 못 판 손실은 그대로 실현된다.

실행: uv run python test_ensemble.py
"""

import os

import ensemble
from ensemble import ask_model, combine, models

U = ["005930", "000660"]


def d(t, a, r="근거"):
    return {"ticker": t, "action": a, "reason": r}


def acts(out):
    return {x["ticker"]: x["action"] for x in out}


# --- 전원 합의 BUY → BUY (정족수 충족) ---
out = combine({"opus": [d("005930", "BUY")], "sonnet": [d("005930", "BUY")]})
assert acts(out) == {"005930": "BUY"}, out
assert "2/2응답" in out[0]["reason"] and "opus=BUY" in out[0]["reason"], out[0]["reason"]

# --- BUY 만장일치가 깨지면 HOLD (다수결이면 통과했을 2:1도 막는다) ---
out = combine({"a": [d("005930", "BUY")], "b": [d("005930", "BUY")], "c": [d("005930", "HOLD")]})
assert acts(out) == {"005930": "HOLD"}, out

# --- [결함1 회귀] 2/3 SELL은 SELL이다. 만장일치를 걸면 유일한 청산 경로가 막힌다 ---
out = combine({
    "opus": [d("005930", "SELL")],
    "sonnet": [d("005930", "SELL")],
    "haiku": [d("005930", "HOLD")],
})
assert acts(out) == {"005930": "SELL"}, f"2/3 SELL이 막히면 손절 경로가 없다: {out}"

# --- 1 SELL + 1 HOLD(기본 2모델 구성)도 SELL. HOLD는 매도 반대가 아니다 ---
out = combine({"opus": [d("005930", "SELL")], "sonnet": [d("005930", "HOLD")]})
assert acts(out) == {"005930": "SELL"}, out

# --- 반대(BUY)가 하나라도 있으면 SELL 안 된다 → HOLD ---
out = combine({"opus": [d("005930", "SELL")], "sonnet": [d("005930", "BUY")]})
assert acts(out) == {"005930": "HOLD"}, out
assert "opus=SELL" in out[0]["reason"] and "sonnet=BUY" in out[0]["reason"], out[0]["reason"]

# --- [결함2 회귀] 모델 하나만 살아남으면 BUY는 보류 — 단일 모델이 주문을 만들면 안 된다 ---
out = combine({"opus": [d("005930", "BUY", "원문근거")], "sonnet": []})
assert acts(out) == {"005930": "HOLD"}, f"단독 모델의 BUY가 그대로 주문이 된다: {out}"
assert "1/2응답" in out[0]["reason"], out[0]["reason"]  # 몇 개가 응답했는지 반드시 남는다
assert "sonnet=x" in out[0]["reason"], out[0]["reason"]  # 죽은 모델이 보인다
assert "원문근거" in out[0]["reason"], out[0]["reason"]

# --- 단일 모델 설정(AI_ENSEMBLE=0)은 기존대로 통과 — 잃을 교차검증이 애초에 없다 ---
out = combine({"": [d("005930", "BUY", "원문근거")]})
assert acts(out) == {"005930": "BUY"}, f"단일 모델 모드에서 BUY가 전부 막힌다: {out}"

# --- 단, 정족수를 SELL에는 걸지 않는다. 모델이 죽었다고 청산까지 막으면 결함 복귀 ---
out = combine({"opus": [d("005930", "SELL")], "sonnet": []})
assert acts(out) == {"005930": "SELL"}, f"모델 장애가 손절을 막는다: {out}"

# --- [결함5 회귀] 종목 누락은 기권이지 반대표가 아니다 ---
out = combine({  # haiku가 005930을 빠뜨림 → 남은 2표 만장일치 BUY, 정족수 충족
    "opus": [d("005930", "BUY")],
    "sonnet": [d("005930", "BUY")],
    "haiku": [d("000660", "HOLD")],
})
assert acts(out)["005930"] == "BUY", out
assert "haiku=-" in [x for x in out if x["ticker"] == "005930"][0]["reason"], out
# 같은 자리에 명시적 HOLD가 들어오면(=진짜 반대) 결과가 뒤집힌다
out = combine({
    "opus": [d("005930", "BUY")],
    "sonnet": [d("005930", "BUY")],
    "haiku": [d("005930", "HOLD")],
})
assert acts(out)["005930"] == "HOLD", out

# --- 누락으로 표가 정족수 아래로 내려가면 BUY 보류 ---
out = combine({"opus": [d("005930", "SELL"), d("000660", "BUY")], "sonnet": [d("005930", "SELL")]})
assert acts(out) == {"005930": "SELL", "000660": "HOLD"}, out

# --- [결함4 회귀] 원 근거를 reason에 보존한다 — analyze.py가 키워드로 근거를 분류한다 ---
for res in (
    {"opus": [d("005930", "BUY", "VWAP 이격 축소")], "sonnet": [d("005930", "BUY", "x")]},
    {"opus": [d("005930", "BUY", "VWAP 이격 축소")], "sonnet": [d("005930", "SELL", "x")]},  # 불일치
):
    r = combine(res)[0]["reason"]
    assert "VWAP" in r, f"불일치 판단이 근거 분류에서 사라진다: {r}"

# --- 전원 실패 → 빈 리스트 (decide.py가 중단한다) ---
assert combine({"opus": [], "sonnet": []}) == []
assert combine({}) == []

# --- 전원 HOLD도 합의다 (주문은 안 나가지만 기록은 남는다) ---
out = combine({"opus": [d("005930", "HOLD")], "sonnet": [d("005930", "HOLD")]})
assert acts(out) == {"005930": "HOLD"} and "2/2응답" in out[0]["reason"], out

# --- 모델 목록: GEMINI_API_KEY 없으면 gemini만 조용히 빠진다 ---
env = dict(os.environ)
try:
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ["AI_ENSEMBLE"] = "1"
    os.environ["AI_ENSEMBLE_MODELS"] = "opus, sonnet ,gemini-2.5-pro"
    assert models() == ["opus", "sonnet"], models()
    os.environ["GEMINI_API_KEY"] = "x"
    assert models() == ["opus", "sonnet", "gemini-2.5-pro"], models()
    # [결함3 회귀] 같은 모델 중복 지정 → 호출 2배 비용에 자기 자신과의 '합의'
    os.environ["AI_ENSEMBLE_MODELS"] = "opus,opus, sonnet"
    assert models() == ["opus", "sonnet"], models()
    os.environ["AI_ENSEMBLE_MODELS"] = "gemini-2.5-pro"
    os.environ.pop("GEMINI_API_KEY")
    assert models() == [""], "전부 걸러지면 기본 모델 단일 호출로 떨어져야 한다"
    os.environ["AI_ENSEMBLE"] = "0"
    assert models() == [""], "앙상블 off는 모델 미지정 단일 호출"
finally:
    os.environ.clear()
    os.environ.update(env)

# --- ask_model: 모델이 터져도 예외가 아니라 빈 리스트 ---
orig = ensemble.ask_claude
try:
    ensemble.ask_claude = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("타임아웃"))
    assert ask_model("opus", "p", U) == []
    # 유니버스 밖 종목은 validate가 버린다 — 모델이 만들어낸 코드가 주문이 되면 안 된다
    ensemble.ask_claude = lambda *a, **k: [d("999999", "BUY"), d("005930", "BUY")]
    assert ask_model("opus", "p", U) == [d("005930", "BUY")]
finally:
    ensemble.ask_claude = orig

print("test_ensemble OK")

# --- 정족수 우회: 키 없어 모델이 빠져도 정족수는 '설정된 수' 기준 ---
# gemini는 키가 없으면 models()에서 조용히 빠진다. 그걸로 정족수가 1로 내려가면
# "2모델 교차검증" 설정이 단일 모델 주문으로 소리 없이 격하된다.
_saved = {k: os.environ.get(k) for k in ("GEMINI_API_KEY", "AI_ENSEMBLE_MODELS", "AI_ENSEMBLE")}
os.environ.pop("GEMINI_API_KEY", None)
os.environ["AI_ENSEMBLE_MODELS"] = "sonnet,gemini-2.5-pro"
os.environ.pop("AI_ENSEMBLE", None)
assert ensemble.models() == ["sonnet"], ensemble.models()
assert ensemble.configured_count() == 2, "키 없어 빠진 모델도 설정 수에 센다"
buy = ensemble.combine({"sonnet": [{"ticker": "005930", "action": "BUY", "reason": "근거"}]}, ensemble.configured_count())
assert buy[0]["action"] == "HOLD", f"정족수 미달인데 단일 BUY가 통과: {buy}"
sell = ensemble.combine({"sonnet": [{"ticker": "005930", "action": "SELL", "reason": "악재"}]}, ensemble.configured_count())
assert sell[0]["action"] == "SELL", "청산은 정족수로 막으면 안 된다(손실을 못 자른다)"
# 명시적 단일 모델(AI_ENSEMBLE=0)은 잃을 교차검증이 없으니 BUY 통과
os.environ["AI_ENSEMBLE"] = "0"
assert ensemble.configured_count() == 1
b1 = ensemble.combine({"": [{"ticker": "005930", "action": "BUY", "reason": "근거"}]}, ensemble.configured_count())
assert b1[0]["action"] == "BUY", "명시적 단일 모델은 BUY가 나가야 한다"
for k, v in _saved.items():
    if v is None: os.environ.pop(k, None)
    else: os.environ[k] = v
print("정족수 우회 회귀 테스트 OK")
