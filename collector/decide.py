"""AI 판단 배치 — claude -p로 종목별 BUY/SELL/HOLD를 받아 기록하고 자동 주문한다.

흐름: watchlist(N) → 일봉·분봉 지표 요약 → claude -p(JSON) → 검증 →
POST /ai-decisions 기록 → 기록 성공분만 상한 판정 → POST /orders → POST /cron/settle.

LLM은 신뢰 경계 밖이다. 출력은 전부 검증하고(유니버스 밖 종목·알 수 없는
action·중복 폐기), 수량은 LLM이 아니라 plan_orders가 결정한다. 판단 기록과
주문 집행을 분리해 둔 이유도 같다 — AI_AUTOTRADE=0이면 주문만 멎고 기록은 남는다.

주문 경로는 fail-closed다. 장중이 아니거나(체결 엔진이 ordered_at 당일 그 이후
분봉으로만 체결하므로 마감 후 주문은 영원히 PENDING) 계좌 미지정이거나 --date가
오늘이 아니면 판단만 기록하고 주문을 생략한다. 주문 판단에 쓰는 GET이 실패해도
기본값으로 진행하지 않고 중단한다 — 조회 실패는 상한·멱등 키를 통째로 비운다.

사용:
  uv run python decide.py --dry-run          # 쓰기 API 없이 계획만 출력
  uv run --env-file ../.env python decide.py --top 10
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from statistics import mean
from zoneinfo import ZoneInfo

import httpx

from turso import Turso
from universe import krx_listing, watchlist

KST = ZoneInfo("Asia/Seoul")
log = logging.getLogger(__name__)

API = (os.environ.get("APP_BASE_URL") or "https://k-papertrade.vercel.app").rstrip("/") + "/api/v1"
SOURCE = "claude-p"


def _int_env(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


# 안전장치 기본값 — "사고가 나도 소액"이 되도록 보수적으로 잡는다.
# 전부 env로만 올릴 수 있고, 코드 경로에서는 절대 우회되지 않는다.
MAX_ORDER_KRW = _int_env("AI_MAX_ORDER_KRW", 1_000_000)  # 1회 주문금액 상한
MAX_QTY = _int_env("AI_MAX_QTY", 100)  # 1회 주문수량 상한
MAX_POSITION_PCT = _int_env("AI_MAX_POSITION_PCT", 20)  # 종목당 최대 비중(평가액 대비 %)
MAX_ORDERS_PER_DAY = _int_env("AI_MAX_ORDERS_PER_DAY", 5)


def autotrade_on() -> bool:
    """킬 스위치. AI_AUTOTRADE=1일 때만 주문이 나간다(기본 꺼짐)."""
    return (os.environ.get("AI_AUTOTRADE") or "0") == "1"


def market_open(now: datetime) -> bool:
    """평일 09:00~15:29 KST. lib/market-hours.ts의 isMarketOpen과 같되 15:30을 뺐다 —
    체결은 접수 시각보다 '뒤' 분봉에서만 일어나므로 마지막 봉(15:30)에 낸 주문은
    체결될 봉이 없다."""
    if now.weekday() >= 5:
        return False
    return 9 * 60 <= now.hour * 60 + now.minute < 15 * 60 + 30


def order_block_reason(date: str, now: datetime, account: int) -> str | None:
    """주문 경로를 막을 이유. None이면 통과. 순수 함수 — 테스트가 직접 검증한다.

    셋 다 "주문이 나가면 안 되는데 나가는" 경로를 막는다.
    - 장중 아님: 서버가 ordered_at을 자기 시각으로 찍고 체결은 그 이후 당일 분봉만
      본다. 마감 후 접수분은 볼 분봉이 없어 영구 PENDING이 된다.
    - 과거 date: 주문의 ordered_at은 언제나 오늘이라 --date를 바꾸면 멱등 키와
      일일 상한이 동시에 비어 중복·초과 주문이 된다. --date는 지표 기준일 전용이다.
    - 계좌 미지정: 자동 선택하면 남의(사람) 계좌에 AI 주문이 들어간다.
    """
    today = now.strftime("%Y-%m-%d")
    if date != today:
        return f"지표 기준일 {date} != 오늘 {today} (--date는 지표 전용)"
    if not account:
        return "AI_ACCOUNT_ID 미설정"
    if not market_open(now):
        return f"장중 아님 {now:%Y-%m-%d %H:%M} KST (평일 09:00~15:29만 주문)"
    return None


# ---------------------------------------------------------------- 지표


def daily_features(mdb: Turso, tickers: list[str], date: str) -> dict[str, dict]:
    """일봉 60개에서 등락률·이동평균 이격·거래량비를 뽑는다."""
    ph = ",".join("?" * len(tickers))
    rows = mdb.query(
        f"SELECT ticker, date, close, volume FROM daily_prices "
        f"WHERE ticker IN ({ph}) AND date <= ? ORDER BY ticker, date",
        (*tickers, date),
    )
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(str(r["ticker"]), []).append(r)

    out = {}
    for t, rs in by.items():
        rs = rs[-60:]
        c = [int(r["close"]) for r in rs]
        v = [int(r["volume"]) for r in rs]
        if not c:
            continue

        def chg(n: int) -> float | None:
            return round((c[-1] / c[-n - 1] - 1) * 100, 2) if len(c) > n and c[-n - 1] else None

        out[t] = {
            "close": c[-1],
            "date": str(rs[-1]["date"]),
            "n": len(c),
            "chg1": chg(1),
            "chg5": chg(5),
            "chg20": chg(20),
            "ma5_gap": round((c[-1] / mean(c[-5:]) - 1) * 100, 2) if len(c) >= 5 else None,
            "ma20_gap": round((c[-1] / mean(c[-20:]) - 1) * 100, 2) if len(c) >= 20 else None,
            "vol_ratio": round(v[-1] / mean(v[-20:]), 2) if len(v) >= 20 and mean(v[-20:]) else None,
        }
    return out


def intraday_features(tickers: list[str], date: str) -> dict[str, dict]:
    """당일 1분봉에서 장중 지표를 뽑는다 — 이 프로젝트의 판단 근거는 분봉이다.

    이전에는 로컬 parquet에 의존했는데 Actions에는 그 파일이 없어(collect는 별도 잡)
    장중 지표가 통째로 빠진 채 일봉만으로 판단하고 있었다. 프로바이더에서 직접 받는다.

    부수효과가 없다는 점도 중요하다: 앱의 /quotes는 서버가 캐시를 쓰고 PENDING 주문을
    정산하는 쓰기 경로라, 판단 단계에서 부르면 드라이런조차 체결을 일으킨다.

    분봉이 비면 휴장이거나 아직 장이 안 열린 것 — 호출측이 주문을 건너뛴다.
    """
    from providers import make_provider

    try:
        provider = make_provider()
    except Exception as e:  # 키 미설정 등 — 일봉만으로 진행
        log.warning("분봉 프로바이더 사용 불가(%s) — 장중 지표 없이 진행", e)
        return {}

    out: dict[str, dict] = {}
    for t in tickers:
        try:
            bars = provider.get_minute_bars(t, date)
        except Exception as e:
            log.warning("%s 분봉 조회 실패: %s", t, e)
            continue
        if not bars:
            continue
        opens = bars[0].open
        last = bars[-1].close
        high = max(b.high for b in bars)
        low = min(b.low for b in bars)
        vol = sum(b.volume for b in bars)
        amt = sum(b.close * b.volume for b in bars)
        vwap = amt / vol if vol else last
        recent = bars[-30:]
        out[t] = {
            "last": last,
            "day_open": opens,
            "day_high": high,
            "day_low": low,
            "from_open_pct": round((last / opens - 1) * 100, 2) if opens else 0.0,
            # 당일 고저 폭에서 현재가 위치(0=저가, 100=고가) — 눌림인지 고점인지
            "range_pos": round((last - low) / (high - low) * 100) if high > low else 50,
            "vwap_gap": round((last / vwap - 1) * 100, 2) if vwap else 0.0,
            "mom30": round((last / recent[0].open - 1) * 100, 2) if recent[0].open else 0.0,
            "late30_vol_pct": round(sum(b.volume for b in recent) / vol * 100, 1) if vol else 0.0,
            "bars": len(bars),
        }
    return out


def format_row(t: str, name: str, f: dict, intra: dict | None) -> str:
    def pct(k: str) -> str:
        v = f.get(k)
        return "-" if v is None else f"{v:+.2f}%"

    # 일봉 개수를 함께 준다 — 표본이 6개뿐인데 추세를 단정하는 판단을 막기 위해
    s = (
        f"{t} {name} | 일봉 {f.get('n', 0)}개 | 종가 {f['close']:,} "
        f"| 1일 {pct('chg1')} 5일 {pct('chg5')} 20일 {pct('chg20')} "
        f"| MA5이격 {pct('ma5_gap')} MA20이격 {pct('ma20_gap')} "
        f"| 거래량/20일평균 {str(f['vol_ratio']) + '배' if f.get('vol_ratio') is not None else '-'}"
    )
    if intra:
        s += (
            f" || 장중({intra['bars']}봉) 현재 {intra['last']:,} 시가대비 {intra['from_open_pct']:+.2f}%"
            f" 고저위치 {intra['range_pos']}% VWAP이격 {intra['vwap_gap']:+.2f}%"
            f" 최근30분 {intra['mom30']:+.2f}% 거래량비중 {intra['late30_vol_pct']}%"
        )
    return s


def build_prompt(rows: list[str], holdings: dict[str, int]) -> str:
    held = ", ".join(f"{t} {q}주" for t, q in sorted(holdings.items())) or "없음"
    return (
        "당신은 한국 주식 단기 스윙 트레이딩 애널리스트다.\n"
        "아래 종목별 지표만 보고 각 종목에 BUY / SELL / HOLD 중 하나와 한 줄 근거를 정하라.\n\n"
        "출력 규칙 (엄수):\n"
        '- 출력은 JSON 배열 하나뿐이다. 코드펜스·머리말·설명 문장 금지.\n'
        '- 원소 형식: {"ticker":"6자리코드","action":"BUY|SELL|HOLD","reason":"한국어 한 줄 80자 이내"}\n'
        "- 입력에 없는 종목코드를 만들지 마라. 입력 종목마다 정확히 하나씩 답하라.\n"
        "- 보유하지 않은 종목에 SELL을 내지 마라. 확신이 없으면 HOLD.\n"
        "- 수량·금액은 쓰지 마라(시스템이 결정한다).\n\n"
        f"현재 보유: {held}\n\n지표:\n" + "\n".join(rows) + "\n"
    )


# ---------------------------------------------------------------- claude -p


def ask_claude(prompt: str, timeout: int = 300) -> list[dict]:
    """claude -p 호출 → 응답 JSON의 result 텍스트에서 배열을 파싱. 실패하면 빈 리스트."""
    exe = shutil.which("claude")
    if not exe:
        log.error("claude CLI 없음 — 판단 건너뜀")
        return []
    try:
        r = subprocess.run(
            [exe, "-p", "--output-format", "json"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            cwd=tempfile.gettempdir(),  # 저장소 CLAUDE.md·설정을 컨텍스트로 끌어오지 않게
        )
    except subprocess.TimeoutExpired:
        log.error("claude -p 타임아웃(%ds)", timeout)
        return []
    if r.returncode != 0:
        log.error("claude -p 실패(rc=%s): %s", r.returncode, (r.stderr or "")[:500])
        return []
    try:
        text = json.loads(r.stdout)["result"]
    except Exception as e:
        log.error("claude 응답 JSON 파싱 실패: %s / %s", e, r.stdout[:300])
        return []
    return parse_decisions(text)


def parse_decisions(text: str) -> list[dict]:
    """LLM 텍스트에서 JSON 배열을 뽑는다. 코드펜스·앞뒤 잡담을 허용한다."""
    if not isinstance(text, str):
        return []
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        log.error("응답에 JSON 배열 없음: %s", text[:200])
        return []
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        log.error("판단 배열 파싱 실패: %s", e)
        return []
    return items if isinstance(items, list) else []


def validate(items: list, universe: list[str]) -> list[dict]:
    """유니버스 밖 종목·알 수 없는 action·중복을 버린다. 남은 것만 신뢰한다."""
    allowed = set(universe)
    seen: set[str] = set()
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        t = str(it.get("ticker", "")).strip().zfill(6)
        action = str(it.get("action", "")).strip().upper()
        if t not in allowed or action not in ("BUY", "SELL", "HOLD") or t in seen:
            log.warning("판단 폐기: %r", it)
            continue
        seen.add(t)
        out.append({"ticker": t, "action": action, "reason": str(it.get("reason", ""))[:200]})
    return out


# ---------------------------------------------------------------- 주문 계획


def plan_orders(
    decisions: list[dict],
    feats: dict[str, dict],
    portfolio: dict,
    done: set[tuple[str, str]],
    date: str,
    *,
    placed_today: int = 0,
    max_krw: int = MAX_ORDER_KRW,
    max_qty: int = MAX_QTY,
    max_pos_pct: int = MAX_POSITION_PCT,
    max_orders: int = MAX_ORDERS_PER_DAY,
) -> tuple[list[dict], list[tuple[str, str]]]:
    """판단 → 주문. 수량 산정과 모든 상한 판정이 여기 한 곳에 모여 있다.

    반환: (주문 리스트, [(티커, 스킵 사유)]). 순수 함수 — test_decide.py가 직접 검증한다.
    """
    cash = int(portfolio.get("cash", 0))
    equity = int(portfolio.get("equity", 0))
    held = {str(p["ticker"]): int(p["qty"]) for p in portfolio.get("positions", [])}
    value = {str(p["ticker"]): int(p.get("value", 0)) for p in portfolio.get("positions", [])}

    orders: list[dict] = []
    skips: list[tuple[str, str]] = []
    for d in decisions:
        t, action = d["ticker"], d["action"]
        if action == "HOLD":
            continue
        if (t, date) in done:
            skips.append((t, "당일 중복 주문"))
            continue
        if placed_today + len(orders) >= max_orders:
            skips.append((t, f"일일 주문 상한 {max_orders}건"))
            continue
        price = int(feats.get(t, {}).get("close") or 0)
        if price <= 0:
            skips.append((t, "가격 없음"))
            continue

        # MARKET 주문은 접수 시각이 아니라 다음 분봉에서 체결된다. 상한가(+30%)까지
        # 튀어도 금액 상한·현금을 넘지 않도록 버퍼를 얹은 가격으로 수량을 정한다.
        cap = int(price * 1.3)

        if action == "BUY":
            room = equity * max_pos_pct // 100 - value.get(t, 0)  # 종목당 최대 비중
            budget = min(max_krw, cash, room)
            qty = min(budget // cap, max_qty)
            if qty <= 0:
                skips.append((t, f"매수 여력 없음(현금 {cash:,} / 비중여유 {room:,})"))
                continue
            cash -= qty * cap  # 같은 배치 안에서 현금을 중복 사용하지 않게(최악가 기준)
        else:
            qty = min(held.get(t, 0), max_qty, max_krw // cap)
            if qty <= 0:
                skips.append((t, "미보유"))
                continue

        orders.append({"ticker": t, "side": action, "type": "MARKET", "qty": int(qty), "reason": d["reason"]})
    return orders, skips


# ---------------------------------------------------------------- API


def _headers() -> dict:
    secret = os.environ.get("CRON_SECRET")
    return {"x-cron-secret": secret} if secret else {}


class ApiError(Exception):
    """GET 실패. 여기서 기본값으로 진행하면 멱등 키·일일 상한이 통째로 비어
    중복·초과 주문이 나간다. 그래서 조회 실패는 전부 중단(fail-closed)이다."""


def api_get(path: str):
    """읽기는 드라이런에서도 실제로 한다. 실패하면 ApiError."""
    try:
        r = httpx.get(API + path, headers=_headers(), timeout=30.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise ApiError(f"GET {path} 실패: {e}") from e


def api_post(path: str, body: dict | None, dry: bool):
    """성공하면 응답(truthy), 실패하면 None. 호출부가 성공 여부로 분기한다."""
    if dry:
        log.info("[dry-run] POST %s %s", path, json.dumps(body, ensure_ascii=False) if body else "")
        return {"dryRun": True}
    try:
        r = httpx.post(API + path, json=body, headers=_headers(), timeout=60.0)
    except Exception as e:
        log.error("POST %s 실패: %s", path, e)
        return None
    if r.status_code >= 400:
        log.error("POST %s → %s %s", path, r.status_code, r.text[:300])
        return None
    return r.json()


def record_decisions(decisions: list[dict], ts: str, dry: bool) -> list[dict]:
    """판단 기록. 기록에 성공한 것만 주문 후보로 돌려준다.

    기록 실패분을 주문하면 다음 실행의 멱등 컷(당일 기록 있는 종목 스킵)이 그
    종목을 못 걸러 같은 주문이 한 번 더 나간다. 멱등 키가 기록 하나뿐이라 그렇다.
    """
    out = []
    for d in decisions:
        body = {"ticker": d["ticker"], "ts": ts, "action": d["action"],
                "reasonSummary": d["reason"], "source": SOURCE}
        if api_post("/ai-decisions", body, dry):
            out.append(d)
        else:
            log.error("판단 기록 실패 %s — 주문 후보에서 제외", d["ticker"])
    return out


# ---------------------------------------------------------------- main


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(description="AI 판단 배치 (claude -p)")
    p.add_argument("--date", help="지표 기준일 YYYY-MM-DD (기본: 오늘 KST). 오늘이 아니면 주문은 생략")
    p.add_argument("--top", type=int, default=_int_env("AI_TOP_N", 10), help="시총 상위 N종목")
    p.add_argument("--account", type=int, default=_int_env("AI_ACCOUNT_ID", 0))
    p.add_argument("--dry-run", action="store_true", help="기록·주문 API를 호출하지 않고 계획만 출력")
    a = p.parse_args()

    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    date = a.date or today
    ts = now.strftime("%Y-%m-%d %H:%M") if date == today else f"{date} 15:30"
    block = order_block_reason(date, now, a.account)

    mdb = Turso.from_env("KRX_MARKET")
    if mdb is None:
        log.error("TURSO_KRX_MARKET_* env 미설정 — 지표를 만들 수 없다")
        return 1

    listing = krx_listing()
    universe = watchlist(a.top, listing)
    names = {str(r.Code): str(r.Name) for r in listing.itertuples()}
    log.info("유니버스 %d종목: %s", len(universe), ",".join(universe))

    # 멱등성: 오늘 이미 기록된 종목은 판단부터 건너뛴다 — 재실행이 중복 주문을 내지 않는다
    prev = api_get("/ai-decisions?limit=200").get("decisions", [])
    done = {(str(d["ticker"]), str(d["ts"])[:10]) for d in prev if d.get("source") == SOURCE}
    todo = [t for t in universe if (t, date) not in done]
    if len(todo) < len(universe):
        log.info("당일 기록 존재로 제외: %s", ",".join(t for t in universe if t not in todo))
    if not todo:
        log.info("판단할 종목 없음 — 종료")
        return 0

    feats = daily_features(mdb, todo, date)
    intra = intraday_features(todo, date)
    missing = [t for t in todo if t not in feats]
    if missing:
        log.warning("일봉 없음으로 제외: %s", ",".join(missing))
    todo = [t for t in todo if t in feats]
    if not todo:
        log.error("지표를 만들 수 있는 종목이 없음")
        return 1

    # 계좌 자동 선택은 없다 — 미지정이면 주문 자체를 안 한다(order_block_reason)
    account = a.account
    portfolio = {"cash": 0, "equity": 0, "positions": []}
    if account:  # 주문이 막혀도 보유 현황은 프롬프트에 필요하다
        portfolio = api_get(f"/accounts/{account}/portfolio")
    holdings = {str(p["ticker"]): int(p["qty"]) for p in portfolio.get("positions", [])}

    rows = [format_row(t, names.get(t, ""), feats[t], intra.get(t)) for t in todo]
    prompt = build_prompt(rows, holdings)
    log.info("프롬프트 %d자 — claude -p 호출", len(prompt))
    decisions = validate(ask_claude(prompt), todo)
    if not decisions:
        log.error("유효한 판단 없음")
        return 1
    for d in decisions:
        log.info("판단 %s %s — %s", d["ticker"], d["action"], d["reason"])

    recorded = record_decisions(decisions, ts, a.dry_run)

    # 게이트를 주문 직전에 **다시** 판정한다. 시작 시점 검사만으로는 부족하다 —
    # 그 사이에 claude -p(최대 5분)와 여러 네트워크 호출이 끼어들어, 15:20에 시작한
    # 실행이 15:35에 주문을 낼 수 있다. 그러면 그날 분봉에 체결될 봉이 없어
    # 영구 PENDING이 된다(고치려던 결함이 시각만 옮겨 재현되는 셈).
    block = order_block_reason(date, datetime.now(KST), a.account)
    if block:
        log.warning("주문 경로 스킵 — %s", block)
        if not a.dry_run:
            log.warning("판단은 기록됐다 — 오늘 재실행은 멱등 컷에 걸려 주문이 나가지 않는다")
        return 0

    orders_today = [
        o for o in api_get(f"/orders?account_id={account}").get("orders", [])
        if str(o.get("ordered_at", ""))[:10] == today
    ]
    # 주문 가격은 위에서 받은 당일 분봉의 최신 종가를 쓴다. 분봉이 없다는 건
    # 휴장이거나 아직 장이 안 열렸다는 뜻이라 그 종목은 주문 대상에서 빠진다
    # (접수해도 체결될 봉이 없어 영구 PENDING이 되기 때문).
    # /quotes를 쓰지 않는 이유: 그건 읽기가 아니라 서버가 캐시를 쓰고 PENDING 주문을
    # 정산하는 경로라, 판단 단계에서 부르면 드라이런조차 체결을 일으킨다.
    live = {
        t: {**feats[t], "close": intra[t]["last"]}
        for t in (d["ticker"] for d in recorded if d["action"] != "HOLD")
        if t in feats and t in intra and intra[t].get("last")
    }

    orders, skips = plan_orders(recorded, live, portfolio, done, today, placed_today=len(orders_today))
    for t, why in skips:
        log.info("주문 스킵 %s — %s", t, why)
    if not orders:
        log.info("주문 없음")
        return 0

    if not autotrade_on():
        log.warning("AI_AUTOTRADE=0 (킬 스위치) — 판단만 기록, 주문 %d건 생략: %s",
                    len(orders), ", ".join(f"{o['side']} {o['ticker']} {o['qty']}주" for o in orders))
        return 0

    for o in orders:
        log.info("주문 %s %s %d주 (@%s)", o["side"], o["ticker"], o["qty"], f"{live[o['ticker']]['close']:,}")
        api_post("/orders", {"accountId": account, "ticker": o["ticker"], "side": o["side"],
                             "type": o["type"], "qty": o["qty"]}, a.dry_run)
    api_post("/cron/settle", None, a.dry_run)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ApiError as e:
        logging.getLogger(__name__).error("%s — 주문 없이 중단(fail-closed)", e)
        sys.exit(1)
