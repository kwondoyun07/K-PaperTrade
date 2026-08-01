from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MinuteBar:
    ticker: str
    ts: str  # 'YYYY-MM-DD HH:MM' KST
    open: int
    high: int
    low: int
    close: int
    volume: int  # 분당 거래량


class DataProvider(Protocol):
    """시세 프로바이더 공통 인터페이스 — 구현체 교체(네이버 → 키움)를 전제로 한다."""

    def get_minute_bars(self, ticker: str, date: str | None = None) -> list[MinuteBar]:
        """date='YYYY-MM-DD'면 해당 거래일, None이면 제공되는 전체 범위."""
        ...

    def get_daily_bars(self, ticker: str, start: str, end: str) -> list[dict]:
        ...

    def get_quote(self, ticker: str) -> dict:
        ...
