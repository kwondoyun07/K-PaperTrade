"""멀티모델 앙상블 — 여러 모델이 같은 프롬프트로 판단하고, 불일치를 확신도로 쓴다.

합의 규칙은 **BUY와 SELL에 비대칭**이다. 대칭 만장일치(전원 같은 action)는 매수만
지키는 게 아니라 매도까지 막는데, 이 시스템에 AI 판단 밖의 손절·청산 경로가 없다
(SELL을 만드는 곳은 decide.py의 이 경로뿐). 그래서 2/3가 팔자여도 못 파는 = 손실을
못 자르는 결함이 된다. 잘못 안 사는 비용은 기회손실이지만 못 파는 비용은 실손실이다.

  BUY  : 투표한 모델이 전원 BUY + 정족수(QUORUM) 이상 응답. 신규 리스크라 확신이 필요.
  SELL : SELL이 하나라도 있고 BUY가 하나도 없으면 SELL. HOLD는 "팔 이유를 못 봤다"일
         뿐 매도 반대가 아니고, 진짜 반대는 BUY 하나뿐이다. 정족수도 안 건다 —
         응답 모델이 하나로 줄어든 상황에서 청산까지 막으면 원래 결함으로 되돌아간다.
  그 외 : HOLD.

모델 하나가 죽어도(타임아웃·rc!=0·파싱 실패) 나머지로 진행하되, 몇 개가 응답했는지와
누가 무엇에 투표했는지를 reason에 남긴다(x=모델 실패, -=응답했으나 그 종목 누락).
"종목을 빠뜨렸다"는 반대표가 아니라 기권이라 만장일치 판정에서 빠진다. 전원 실패면
빈 리스트를 돌려주고 decide.py가 기존대로 중단한다.

모델 목록은 AI_ENSEMBLE_MODELS(쉼표, 중복 제거). gemini*는 GEMINI_API_KEY가 있을 때만
붙고 없으면 조용히 빠진다. AI_ENSEMBLE=0이면 모델 지정 없이 한 번만 부른다(기존 동작).
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor

import httpx

from decide import ask_claude, parse_decisions, validate

log = logging.getLogger(__name__)

# claude 별칭은 `claude -p --model`로 실측 확인(opus→claude-opus-5, sonnet→claude-sonnet-5).
# gemini 모델명은 키가 생기면 env로 갈아끼운다.
DEFAULT_MODELS = "opus,sonnet,gemini-2.5-pro"

# BUY에 필요한 최소 응답 모델 수. 2인 이유: 기본 구성이 실질 2모델(gemini는 키가 없어
# 빠짐)이라 3을 걸면 BUY가 영영 안 나오고, 1이면 모델 하나가 죽는 순간 교차검증이
# 통째로 사라진 채 단일 모델이 조용히 주문을 만든다(원래 결함). SELL에는 안 건다.
QUORUM = 2


def models() -> list[str]:
    """호출할 모델 목록. 빈 문자열 하나 = 모델 미지정(claude 기본) 단일 판단."""
    if (os.environ.get("AI_ENSEMBLE") or "1") != "1":
        return [""]
    out = []
    # 중복 제거: 같은 모델을 두 번 부르면 비용만 2배로 들고, 스스로와의 '합의'가
    # 교차검증인 척 만장일치를 통과시킨다(같은 모델 = 같은 편향).
    for m in dict.fromkeys(
        m.strip() for m in (os.environ.get("AI_ENSEMBLE_MODELS") or DEFAULT_MODELS).split(",")
    ):
        if not m:
            continue
        if m.startswith("gemini") and not os.environ.get("GEMINI_API_KEY"):
            log.info("GEMINI_API_KEY 없음 — %s 건너뜀", m)
            continue
        out.append(m)
    return out or [""]


def configured_count() -> int:
    """설정에 적힌 모델 수(키가 없어 빠진 것 포함). 정족수 기준 — 조용한 격하를 막는다."""
    if (os.environ.get("AI_ENSEMBLE") or "1") != "1":
        return 1
    names = dict.fromkeys(
        m.strip() for m in (os.environ.get("AI_ENSEMBLE_MODELS") or DEFAULT_MODELS).split(",")
    )
    return len([m for m in names if m]) or 1


def ask_gemini(model: str, prompt: str, timeout: int) -> list[dict]:
    r = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=timeout,
    )
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return parse_decisions("".join(p.get("text", "") for p in parts))


def ask_model(model: str, prompt: str, universe: list[str], timeout: int = 300) -> list[dict]:
    """한 모델의 판단. 어떤 실패든 빈 리스트 — 한 모델 장애가 배치를 멈추면 안 된다."""
    try:
        items = (
            ask_gemini(model, prompt, timeout)
            if model.startswith("gemini")
            else ask_claude(prompt, timeout, model or None)
        )
    except Exception as e:
        log.error("%s 호출 실패: %s", model or "claude", e)
        return []
    out = validate(items, universe)
    log.info("%s 판단 %d건", model or "claude", len(out))
    return out


def combine(results: dict[str, list[dict]], configured: int | None = None) -> list[dict]:
    """모델별 판단 → 합의 판단. 순수 함수 — test_ensemble.py가 직접 검증한다.

    규칙은 모듈 docstring 참조(BUY=만장일치+정족수, SELL=반대(BUY) 없으면 채택).

    reason은 언제나 `[투표 →결정 n/N응답] 원근거` 한 형식이다. 원근거를 그대로 뒤에
    붙이는 건 analyze.py가 reason_summary 키워드로 근거를 분류하기 때문 — 투표 내역만
    남기면 그 판단이 근거 분류에서 통째로 사라진다(합의든 불일치든 똑같이 보존한다).
    """
    asked = list(results)
    live = {m: {d["ticker"]: d for d in ds} for m, ds in results.items() if ds}
    if not live:
        log.error("응답한 모델 없음")
        return []
    # 정족수는 **설정된 모델 수** 기준이다(요청된 수가 아니라). gemini는 키가 없으면
    # models()에서 조용히 빠지는데, 그걸로 정족수가 내려가면 "2모델 교차검증" 설정이
    # 단일 모델 주문으로 소리 없이 격하된다. 명시적으로 1모델만 설정한 경우(AI_ENSEMBLE=0)
    # 에만 1로 내린다 — 그건 잃을 교차검증이 애초에 없는 의도된 설정이다.
    quorum = min(QUORUM, configured if configured is not None else len(asked))
    if configured is not None and configured > len(asked):
        log.error("설정 %d모델 중 %d개만 사용 가능 — 정족수 %d 유지(BUY 보류 가능)",
                  configured, len(asked), quorum)
    if len(live) < len(asked):
        log.error("모델 %d/%d만 응답 — BUY는 정족수 %d 미만이면 보류(SELL은 그대로)",
                  len(live), len(asked), quorum)

    out = []
    for t in dict.fromkeys(t for byt in live.values() for t in byt):
        # x=모델 자체가 실패, -=응답했지만 이 종목을 빠뜨림. 둘 다 기권이지 반대표가 아니다.
        votes = {m: live[m].get(t, {}).get("action", "-") if m in live else "x" for m in asked}
        cast = [a for a in votes.values() if a in ("BUY", "SELL", "HOLD")]
        acts = set(cast)
        if acts == {"BUY"} and len(cast) >= quorum:
            action = "BUY"
        elif "SELL" in acts and "BUY" not in acts:
            action = "SELL"
        else:
            action = "HOLD"
        # 채택된 action에 투표한 모델의 근거를 우선 보존한다 — SELL로 나가는데 HOLD 근거가
        # 붙으면 사후 분석에서 그 매도를 오독한다. 아무도 그 action을 안 냈으면(불일치→HOLD) 첫 근거.
        picks = [live[m][t] for m in asked if m in live and t in live[m]]
        first = next((p["reason"] for p in picks if p["action"] == action), picks[0]["reason"])
        tag = " ".join(f"{m or 'claude'}={v}" for m, v in votes.items())
        log.info("합의 %s %s ← %s", t, action, votes)
        out.append({
            "ticker": t,
            "action": action,
            "reason": f"[{tag} →{action} {len(cast)}/{len(asked)}응답] {first}"[:200],
        })
    return out


def decide_all(prompt: str, universe: list[str], timeout: int = 300) -> list[dict]:
    """모델들을 병렬 호출해 합의 판단을 만든다. 순차면 모델 수만큼 느려진다."""
    ms = models()
    log.info("앙상블 %d모델 병렬 호출: %s", len(ms), ", ".join(m or "claude" for m in ms))
    with ThreadPoolExecutor(max_workers=len(ms)) as ex:
        futs = [ex.submit(ask_model, m, prompt, universe, timeout) for m in ms]
        results = {m: f.result() for m, f in zip(ms, futs)}
    return combine(results, configured_count())
