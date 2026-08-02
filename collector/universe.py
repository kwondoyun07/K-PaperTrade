"""KRX 전 종목 목록 — FinanceDataReader KRX 스냅샷.

fdr.StockListing('KRX')는 종목 목록과 함께 최근 거래일의 OHLCV 스냅샷
(Open/High/Low/Close/Volume, int64·NaN 없음 — 2026-08-01 실측)을 담고 있어
daily.py의 일봉 폴백 소스로도 재사용한다.
"""

import FinanceDataReader as fdr
import pandas as pd


def krx_listing() -> pd.DataFrame:
    return fdr.StockListing("KRX")


def watchlist(n: int = 50, listing: pd.DataFrame | None = None) -> list[str]:
    """시가총액 상위 n종목 (KOSPI+KOSDAQ). 과거 분봉 백필 대상 선정용.

    전 종목 1년치는 키움 초당 1회 제한 때문에 80시간대라 비현실적이다.
    전략 검증은 유동성 있는 종목에서 하는 게 의미도 크므로 시총 상위로 좁힌다.
    """
    df = listing if listing is not None else krx_listing()
    df = df[~df["Market"].astype(str).str.upper().str.contains("KONEX")]
    top = df.nlargest(n, "Marcap")
    return [str(c) for c in top["Code"]]


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
