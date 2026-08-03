"""무료 애널리스트 컨센서스·리포트 수집 — 네이버 모바일 스톡 API.

종목당 JSON 한 번으로 목표주가 컨센서스·투자의견·최근 증권사 리포트·밸류에이션을
받는다. 무료·무키·무(無)HTML파싱. 실패는 None — 컨센서스는 판단을 풍부하게 하는
보조 신호이지 필수 경로가 아니므로, 없으면 기술적 지표만으로 판단을 이어간다.

파싱(parse_integration)은 순수 함수로 분리해 네트워크 없이 검증한다(test_reports.py).
"""

import logging
import re
import time

import httpx

log = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
_HEADERS = {"User-Agent": _UA, "Referer": "https://m.stock.naver.com/"}
_BASE = "https://m.stock.naver.com/api/stock"


def _num(v: object) -> int | None:
    """'493,542' → 493542. 숫자로 안 떨어지면 None."""
    try:
        return int(str(v).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _mmdd(yyyymmdd: object) -> str:
    s = str(yyyymmdd or "")
    return f"{s[4:6]}/{s[6:8]}" if len(s) == 8 else s


def _clean(v: object, limit: int) -> str:
    """리포트 제목·증권사명은 외부 텍스트다 — 개행·연속공백을 접어 프롬프트 행
    구조를 흉내내지 못하게 하고 길이를 자른다(프롬프트 주입 표면 축소)."""
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def parse_integration(d: dict) -> dict:
    """네이버 integration 응답 → 컨센서스 신호. 순수 함수.

    필드가 예상 타입이 아니어도(리스트가 아닌 등) 죽지 않고 빈 신호로 떨어진다.
    """
    ci = d.get("consensusInfo")
    ci = ci if isinstance(ci, dict) else {}
    ti = d.get("totalInfos")
    tot = {t.get("code"): t.get("value") for t in ti if isinstance(t, dict)} if isinstance(ti, list) else {}
    rs = d.get("researches")
    reports = [
        {"broker": _clean(r.get("bnm"), 20), "title": _clean(r.get("tit"), 80), "date": _mmdd(r.get("wdt"))}
        for r in (rs if isinstance(rs, list) else [])[:5]
        if isinstance(r, dict) and r.get("tit")
    ]
    return {
        "target_mean": _num(ci.get("priceTargetMean")),  # 목표주가 컨센서스(원)
        "recomm_mean": ci.get("recommMean"),  # 투자의견 1~5, 높을수록 매수
        "consensus_date": ci.get("createDate"),
        "cns_per": tot.get("cnsPer"),  # 추정 PER
        "pbr": tot.get("pbr"),
        "div_yield": tot.get("dividendYieldRatio"),
        "hi52": _num(tot.get("highPriceOf52Weeks")),
        "lo52": _num(tot.get("lowPriceOf52Weeks")),
        "reports": reports,
    }


def fetch_consensus(ticker: str, client: httpx.Client) -> dict | None:
    try:
        r = client.get(f"{_BASE}/{ticker}/integration", headers=_HEADERS, timeout=10.0)
        r.raise_for_status()
        return parse_integration(r.json())
    except Exception as e:  # 네트워크·JSON·구조 변경 — 보조 신호라 조용히 스킵
        log.warning("컨센서스 조회 실패 %s: %s", ticker, e)
        return None


def fetch_many(tickers: list[str]) -> dict[str, dict]:
    """유니버스(보통 ~10종목) 컨센서스를 순차로 받는다. 실패한 종목은 빠진다."""
    out: dict[str, dict] = {}
    with httpx.Client(follow_redirects=True) as c:
        for i, t in enumerate(tickers):
            if i:
                time.sleep(0.25)  # 연속 호출 예의 — 소규모라 이 정도면 차단 회피에 충분
            v = fetch_consensus(t, c)
            if v:
                out[t] = v
    if out:
        log.info("컨센서스 수집: %d/%d종목", len(out), len(tickers))
    return out
