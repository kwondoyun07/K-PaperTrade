"""KRX 전 종목 목록 — FinanceDataReader KRX 스냅샷.

fdr.StockListing('KRX')는 종목 목록과 함께 최근 거래일의 OHLCV 스냅샷
(Open/High/Low/Close/Volume, int64·NaN 없음 — 2026-08-01 실측)을 담고 있어
daily.py의 일봉 폴백 소스로도 재사용한다.
"""

import os
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd

# 코어 ETF — 코어·위성 구조(docs/core-satellite.md)에서 시장 수익을 맡는다. AI 판단 대상이
# 아니고, ETF 중 유일하게 일봉을 수집한다. 화면(components/Dashboard.tsx)도 같은 값을 쓴다.
CORE_TICKER = os.environ.get("AI_CORE_TICKER") or "069500"


def holiday_verdict(date: str, lookback: int = 10) -> str | None:
    """분봉·당일 FDR이 동시에 빈 날의 휴장 여부. 'holiday' | 'traded' | None(판정 불가).

    당일 조회 하나로는 '휴장'과 '소스 장애'가 구분되지 않는다. 그래서 **구간**으로 묻는다:
    최근 lookback일에 지수 데이터가 있는데 이 날짜만 없으면 휴장이고, 구간이 통째로
    비면 소스가 죽은 것이다(그때만 판정 불가).

    daily.py에 있던 것을 여기로 옮겼다 — decide.py도 휴장일엔 판단을 안 하려면 써야 하는데,
    daily를 import하면 pykrx까지 딸려온다. universe는 fdr만 쓴다.
    """
    base = datetime.strptime(date, "%Y-%m-%d")
    start = (base - timedelta(days=lookback)).strftime("%Y-%m-%d")
    try:
        df = fdr.DataReader("KS11", start, date)
    except Exception:
        return None
    if df.empty:
        return None  # 구간이 통째로 빔 = FDR 장애
    return "traded" if date in {str(i)[:10] for i in df.index} else "holiday"


def krx_listing() -> pd.DataFrame:
    return fdr.StockListing("KRX")


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
