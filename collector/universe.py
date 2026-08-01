"""KRX 전 종목 목록 — FinanceDataReader KRX 스냅샷.

fdr.StockListing('KRX')는 종목 목록과 함께 최근 거래일의 OHLCV 스냅샷
(Open/High/Low/Close/Volume, int64·NaN 없음 — 2026-08-01 실측)을 담고 있어
daily.py의 일봉 폴백 소스로도 재사용한다.
"""

import FinanceDataReader as fdr
import pandas as pd


def krx_listing() -> pd.DataFrame:
    return fdr.StockListing("KRX")


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
