import logging
import os

from .base import DataProvider, MinuteBar
from .kiwoom import KiwoomProvider
from .naver import NaverProvider

log = logging.getLogger(__name__)

__all__ = ["DataProvider", "MinuteBar", "KiwoomProvider", "NaverProvider", "make_provider"]


def make_provider(name: str | None = None) -> DataProvider:
    """기본은 키움(공식·히스토리 5개월+). 키가 없으면 네이버로 폴백.

    네이버는 최근 ~6거래일만 제공하므로 당일 수집에는 쓸 수 있지만
    과거 백필에는 못 쓴다. 소스 선택은 PROVIDER env 또는 인자로 강제 가능.
    """
    name = (name or os.environ.get("PROVIDER") or "").lower()
    if name == "naver":
        return NaverProvider()
    if name == "kiwoom":
        return KiwoomProvider()
    if os.environ.get("KIWOOM_APP_KEY") and os.environ.get("KIWOOM_APP_SECRET"):
        return KiwoomProvider()
    log.warning("KIWOOM_APP_KEY 미설정 — 네이버로 폴백 (과거 백필 불가, 최근 ~6거래일만)")
    return NaverProvider()
