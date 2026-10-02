"""KRX 전 종목 목록·시총 순위·휴장 판정 — FinanceDataReader KRX 스냅샷.

fdr.StockListing('KRX')는 종목 목록(코드·이름·시장)과 시가총액을 준다. 같이 딸려 오는
OHLCV는 '캐시가 만들어진 시각'의 값이라 종가가 아니다 — 일봉 소스로 쓰지 않는다
(쓰던 때 정오 값·시간외 값이 종가로 들어갔다. 일봉은 daily.py가 분봉에서 파생한다).
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import FinanceDataReader as fdr
import pandas as pd

KST = ZoneInfo("Asia/Seoul")

# 코어 ETF — 코어·위성 구조(docs/core-satellite.md)에서 시장 수익을 맡는다. AI 판단 대상이
# 아니고, ETF 중 유일하게 일봉을 수집한다. 화면(components/Dashboard.tsx)도 같은 값을 쓴다.
CORE_TICKER = os.environ.get("AI_CORE_TICKER") or "069500"


def holiday_verdict(date: str, lookback: int = 10) -> str | None:
    """분봉 프로브가 빈 날의 휴장 여부. 'holiday' | 'traded' | None(판정 불가).

    **장 마감 뒤(collect)에만 쓴다.** 지수 소스는 장 시작 전엔 당일 행이 없어서, 장중 판단
    (decide)에 쓰면 거래일을 휴장으로 보고 하루를 통째로 건너뛴다 — decide는 당일 분봉이
    있는지로 직접 본다.

    지수 일봉에 그 날짜가 있으면 거래일, 소스가 그 날짜를 덮는데 없으면 휴장이다. FDR이
    그 날짜까지 못 오면(2026-09-17에서 멎었다 — 그 뒤 거래일 4일을 'holiday'로 오판하는
    값을 냈다) 네이버 지수로 묻는다. 네이버는 최근 20거래일만 주므로 그보다 옛 날짜는 판정 불가.
    """
    base = datetime.strptime(date, "%Y-%m-%d")
    start = (base - timedelta(days=lookback)).strftime("%Y-%m-%d")
    try:
        days = {str(i)[:10] for i in fdr.DataReader("KS11", start, date).index}
    except Exception:
        days = set()
    if not days or max(days) < date:
        try:
            from providers.naver import NaverProvider

            days = {r[1] for r in NaverProvider().get_index_prices("KOSPI", 20)}
        except Exception:
            return None
        if not days or date < min(days):
            return None
    return "traded" if date in days else "holiday"


def krx_listing() -> pd.DataFrame:
    return fdr.StockListing("KRX")


# FDR이 읽는 캐시 저장소. 2026-09-11부터 당일 파일의 새벽판(03~06시 커밋)은 Marcap·Close가
# 전부 비어 있고 이름순이다 — 그대로 nlargest를 하면 앞 10행(3S, AJ네트웍스 …)이 '시총 상위'로
# 나온다. 실제로 9/14~10/1의 10:30 사이클(9/28부터는 12:30도) 16번이 그 10종목을 판단했다.
CACHE_URL = ("https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/"
             "refs/heads/master/data/listing/krx/{}.csv")
_CACHE_DTYPE = {"Code": str, "Dept": str, "ChangeCode": str, "MarketId": str}  # FDR과 같은 인자


def marcap_ok(df: pd.DataFrame | None) -> bool:
    """시총 순위를 매길 수 있는 목록인가. 새벽판(전부 NaN)과 잘린 응답을 거른다."""
    if df is None or len(df) < 1000 or "Marcap" not in df:
        return False
    return bool((pd.to_numeric(df["Marcap"], errors="coerce") > 0).mean() > 0.9)


def cached_listing(days: int = 10) -> pd.DataFrame:
    """캐시 저장소에서 Marcap이 온전한 가장 최근 파일. KRX 포털이 죽어도 동작한다.

    오늘 파일부터 본다(정오 이후엔 오늘 것이 온전하다). 10일인 이유: 추석 연휴처럼
    거래일 간격이 8일까지 벌어진다. 전부 실패하면 예외 — 호출측이 다음 폴백으로 넘어간다.
    """
    today = datetime.now(KST)
    for back in range(days + 1):
        d = (today - timedelta(days=back)).strftime("%Y-%m-%d")
        try:
            df = pd.read_csv(CACHE_URL.format(d), index_col=0, dtype=_CACHE_DTYPE).reset_index(drop=True)
        except Exception:  # 404(휴일)·네트워크 — 하루 더 거슬러 간다
            continue
        if marcap_ok(df):
            return df
    raise ValueError(f"최근 {days}일 캐시에 시총이 온전한 상장목록이 없다")


def _etf_codes() -> set[str]:
    """KRX ETF 종목코드. StockListing('KRX')에 ETF가 시총 상위로 섞여 들어와
    (예: 채권형 ETF), 걸러내지 않으면 AI가 현금성 자산을 매매한다."""
    try:
        return set(fdr.StockListing("ETF/KR")["Symbol"].astype(str))
    except Exception:
        return set()  # 목록 실패 시 제외 안 함(진행은 계속)


def watchlist(n: int = 50, listing: pd.DataFrame | None = None) -> list[str]:
    """시가총액 상위 n종목 (KOSPI+KOSDAQ, ETF 제외). 매매·백필 대상 선정용.

    전 종목 1년치는 키움 초당 1회 제한 때문에 80시간대라 비현실적이다.
    전략 검증은 유동성 있는 종목에서 하는 게 의미도 크므로 시총 상위로 좁힌다.
    ETF는 제외한다 — 시총 상위에 채권/현금성 ETF가 섞여 매매되면 안 되므로.
    """
    df = listing if listing is not None else krx_listing()
    if not marcap_ok(df):
        # 검증 없이 nlargest를 하면 NaN뿐인 목록에서 앞 n행이 조용히 나온다(예외도 경고도 없다).
        df = cached_listing()
    df = df[~df["Market"].astype(str).str.upper().str.contains("KONEX")]
    df = df[~df["Code"].astype(str).isin(_etf_codes())]
    top = df.nlargest(n, "Marcap")
    return [str(c) for c in top["Code"]]


def etf_stocks() -> list[dict]:
    """상장 ETF (코드·이름). FDR의 KRX 목록에는 ETF가 아예 없어서(2,873종목 중 0건)
    이걸 따로 받아야 화면에 이름이 뜬다 — 실측: 153130이 stocks에 없어 코드로만 표시됐다.

    **이름·검색용이다. 수집 유니버스(krx_stocks)에는 넣지 않는다** — ETF 1,100여 개의
    분봉까지 받으면 키움 초당 1회 제한 때문에 수집이 20분 넘게 늘어난다.
    """
    try:
        df = fdr.StockListing("ETF/KR")
    except Exception:
        return []  # 이름은 부가정보 — 실패해도 배치를 막지 않는다
    return [
        {"ticker": str(r.Symbol), "name": str(r.Name), "market": "ETF"}
        for r in df.itertuples()
        if str(r.Symbol).strip()
    ]


def krx_stocks(listing: pd.DataFrame | None = None) -> list[dict]:
    """KOSPI+KOSDAQ 전 종목 (KONEX 제외), 티커 정렬."""
    df = listing if listing is not None else krx_listing()
    out = []
    for r in df.itertuples():
        market = str(r.Market).upper()
        if "KONEX" in market:
            continue
        out.append(
            {
                "ticker": str(r.Code),
                "name": str(r.Name),
                "market": "KOSDAQ" if "KOSDAQ" in market else "KOSPI",
            }
        )
    out.sort(key=lambda s: s["ticker"])
    return out
