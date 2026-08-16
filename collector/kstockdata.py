"""한국주식데이터(aikstockdata.com) 클라이언트 — 무료·무키·CORS 개방 백업 소스.

시세는 T+1 확정치(금융위 공공데이터포털)라 daily.py의 **당일 폴백으로는 못 쓴다**.
2026-08-16 실측: 공개된 마지막 시세가 08-13인데 우리 daily_prices는 이미 08-14를
갖고 있었다. 폴백은 pykrx/FDR이 실패한 그날 밤 그 날짜를 대신 채워야 하는데
이 소스에는 애초에 그 날짜가 없다. 그래서 폴백 자리에는 배선하지 않는다.

대신 검증으로 확인된 쓸 자리는 셋:
- parse_quotes: 1,462종목 OHLCV가 우리 daily_prices와 **OHLC 0건 불일치**(2026-08-13
  전 종목 대조). 우리 파이프라인 감사·과거 특정일 구멍 메우기에 쓸 수 있다.
  단 거래량은 항상 우리보다 크거나 같다(중앙값 +0.17%, 최대 +24%) — 시간외 포함으로 보인다.
- parse_history: 250거래일 종가·거래량. daily_prices는 시총 상위 50종목만 253일이고
  나머지 ~2,700종목은 17거래일뿐이라 백테스트가 불가능한데, 여기서 무료로 채운다.
  **시가·고가·저가가 없다** — daily_prices(OHLC NOT NULL)에 그대로 넣지 말 것.
  **무보정(unadjusted) 종가다** — 액면분할·병합이 그대로 점프로 남는다. 우리 DB와
  대조 시 48종목 11,949일 중 563일이 불일치했고, 원인은 대부분 코퍼레이트 액션이다.
  수익률 계산에 그대로 쓰면 분할이 -77% 급락으로 잡힌다. 백테스트 전에 반드시 보정하라.
- parse_priors: 공시 유형별 시장조정 초과수익 중앙값. 우리가 직접 산출 못 하는 값.

출처 표기 의무: "자료: 한국주식데이터(aikstockdata.com) — 원천: 금융감독원 DART ·
금융위원회 공공데이터포털"
"""

import httpx

BASE = "https://aikstockdata.com/data/public"
CITATION = (
    "자료: 한국주식데이터(aikstockdata.com) — "
    "원천: 금융감독원 DART · 금융위원회 공공데이터포털"
)


def fetch(path: str, client: httpx.Client | None = None) -> dict:
    """path 예: 'quotes.json', 's/005930_history.json'. 없는 종목은 404."""
    c = client or httpx.Client(timeout=30.0)
    r = c.get(f"{BASE}/{path}")
    r.raise_for_status()
    return r.json()


def _iso(yyyymmdd: object) -> str:
    s = str(yyyymmdd)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def parse_quotes(payload: dict) -> list[dict]:
    """quotes.json → daily_prices 스키마 그대로(ticker,date,open,high,low,close,volume).

    거래정지·휴장 종목은 시가·고저·거래량이 0으로 오므로(발행처 명시 결측규칙) 버린다 —
    0원 시가가 들어가면 MA·거래량비가 조용히 망가진다.
    """
    date = _iso(payload["basDt"])
    out = []
    for i in payload["items"]:
        if not (i["mkp"] and i["hipr"] and i["lopr"] and i["clpr"]):
            continue
        out.append(
            {
                "ticker": i["종목코드"],
                "date": date,
                "open": int(i["mkp"]),
                "high": int(i["hipr"]),
                "low": int(i["lopr"]),
                "close": int(i["clpr"]),
                "volume": int(i["trqu"]),
            }
        )
    return out


def parse_history(payload: dict) -> list[dict]:
    """s/{code}_history.json → [{ticker,date,close,volume}] 250거래일. OHLC 없음."""
    code = payload["code"]
    return [
        {"ticker": code, "date": _iso(d), "close": int(c), "volume": int(v)}
        for d, c, v in payload["rows"]
    ]


def parse_priors(payload: dict, horizon: str = "h5") -> dict[str, dict]:
    """disclosure_impact.json → {공시유형: {excess_pct, up_ratio_pct, n, significant}}.

    significant은 median_ci95가 0을 포함하지 않을 때만 True.

    주의: 이 값은 3주(2026-07-20~08-06, 14거래일)짜리 단일 시장국면 산물이다. 같은
    기간 KOSDAQ 일별 시장수익률 중앙값이 -17.6%~+23.7%로 출렁였다. 유형별 초과수익을
    항구적 성질로 읽지 말고, 표본 기간과 함께 전달하라(h20은 아직 준비 전).
    """
    out = {}
    for s in payload["summary"]:
        h = s.get(horizon)
        if not h or not h.get("enough"):
            continue
        out[s["label"]] = {
            "excess_pct": h["median_excess_pct"],
            "up_ratio_pct": h["up_ratio_pct"],
            "n": h["n"],
            "significant": not h.get("ci_includes_zero", True),
        }
    return out


def quotes(client: httpx.Client | None = None) -> list[dict]:
    return parse_quotes(fetch("quotes.json", client))


def history(code: str, client: httpx.Client | None = None) -> list[dict]:
    """없는 종목은 빈 리스트. 이 소스의 유니버스는 ~1,500이라 우리 watchlist에도 구멍이
    있다(005935 삼성전자우·138040 메리츠금융지주 404 실측) — 종목 순회가 예외로 죽지 않게."""
    try:
        return parse_history(fetch(f"s/{code}_history.json", client))
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return []
        raise


def priors(horizon: str = "h5", client: httpx.Client | None = None) -> dict[str, dict]:
    return parse_priors(fetch("disclosure_impact.json", client), horizon)
