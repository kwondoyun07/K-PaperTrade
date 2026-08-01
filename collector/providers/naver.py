"""네이버 금융 비공식 API 프로바이더.

엔드포인트: https://api.stock.naver.com/chart/domestic/item/{ticker}/minute
2026-08-01 실측 검증:
- periodSizeMinutes=1 + startDateTime/endDateTime(YYYYMMDDHHMM) 파라미터
- 진짜 분봉 OHLC JSON (localDateTime, openPrice, highPrice, lowPrice, currentPrice)
- accumulatedTradingVolume은 이름과 달리 **분당** 거래량 (일합계 ≈ 일봉 거래량 확인)
- 멀티데이 범위를 한 요청으로 조회 가능, 제공 범위는 최근 ~6거래일뿐
  → 매일 적재로 히스토리를 직접 쌓는 것이 필수

비공식 API이므로: 요청 간격 준수(기본 0.5초), 지수 백오프 재시도,
방어적 파싱(불량 항목 스킵+로그), User-Agent 지정. 개인 연구용 저빈도 호출 원칙.
"""

import logging
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from .base import MinuteBar

log = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
BASE = "https://api.stock.naver.com/chart/domestic/item"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def parse_minute(ticker: str, data: object) -> list[MinuteBar]:
    """방어적 파싱: 항목 단위로 검증하고 불량 항목은 스킵. 시각 오름차순 반환."""
    if not isinstance(data, list):
        raise ValueError(f"{ticker}: 예상 밖 응답 형식 {type(data).__name__}")
    bars: list[MinuteBar] = []
    skipped = 0
    for item in data:
        try:
            t = str(item["localDateTime"])  # '20260731090000'
            close = item["currentPrice"]
            if close is None or len(t) < 12:
                skipped += 1
                continue
            c = int(round(float(close)))
            o = item.get("openPrice")
            h = item.get("highPrice")
            lo = item.get("lowPrice")
            o = int(round(float(o))) if o is not None else c
            h = int(round(float(h))) if h is not None else max(o, c)
            lo = int(round(float(lo))) if lo is not None else min(o, c)
            v = item.get("accumulatedTradingVolume")
            v = int(v) if v is not None else 0
            ts = f"{t[0:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}"
            bars.append(MinuteBar(ticker, ts, o, h, lo, c, v))
        except (KeyError, TypeError, ValueError):
            skipped += 1
    if skipped:
        log.warning("%s: 분봉 %d개 항목 파싱 스킵", ticker, skipped)
    bars.sort(key=lambda b: b.ts)
    return bars


class NaverProvider:
    def __init__(self, req_interval: float | None = None, max_retries: int = 3):
        # 초당 1~3요청 원칙 — 기본 0.5초 간격(2req/s), NAVER_REQ_INTERVAL로 조정
        if req_interval is None:
            req_interval = float(os.environ.get("NAVER_REQ_INTERVAL", "0.5"))
        self.req_interval = req_interval
        self.max_retries = max_retries
        self._last_req = 0.0
        self._client = httpx.Client(headers={"User-Agent": UA}, timeout=15.0)

    def _throttle(self) -> None:
        wait = self.req_interval - (time.monotonic() - self._last_req)
        if wait > 0:
            time.sleep(wait)
        self._last_req = time.monotonic()

    def _get_json(self, url: str, params: dict) -> object:
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                r = self._client.get(url, params=params)
                if r.status_code == 200:
                    return r.json()
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    r.raise_for_status()  # 재시도 무의미한 클라이언트 오류
                last_err = RuntimeError(f"HTTP {r.status_code}")
            except httpx.HTTPStatusError:
                raise
            except (httpx.TransportError, ValueError) as e:
                last_err = e
            backoff = 2**attempt  # 1, 2, 4초
            log.warning("naver 요청 실패(%s), %d초 후 재시도: %s", url, backoff, last_err)
            time.sleep(backoff)
        raise RuntimeError(f"naver 요청 재시도 초과: {url} — {last_err}")

    def get_minute_bars(self, ticker: str, date: str | None = None) -> list[MinuteBar]:
        if date:
            d = date.replace("-", "")
            start, end = f"{d}0900", f"{d}1540"
        else:
            # 제공 범위가 ~6거래일이므로 14일 전부터 요청하면 전부 커버된다
            today = datetime.now(KST).date()
            start = (today - timedelta(days=14)).strftime("%Y%m%d") + "0900"
            end = today.strftime("%Y%m%d") + "1540"
        data = self._get_json(
            f"{BASE}/{ticker}/minute",
            {"periodSizeMinutes": 1, "startDateTime": start, "endDateTime": end},
        )
        return parse_minute(ticker, data)

    def get_daily_bars(self, ticker: str, start: str, end: str) -> list[dict]:
        raise NotImplementedError("일봉·수급은 pykrx/FDR 경로 사용 (daily.py 참고)")

    def get_quote(self, ticker: str) -> dict:
        data = self._get_json(f"{BASE}/{ticker}/day", {})
        if not isinstance(data, list) or not data:
            raise ValueError(f"{ticker}: 일봉 응답 없음")
        row = data[-1]
        d = str(row["localDate"])
        return {
            "ticker": ticker,
            "date": f"{d[0:4]}-{d[4:6]}-{d[6:8]}",
            "price": int(round(float(row["closePrice"]))),
            "open": int(round(float(row["openPrice"]))),
            "high": int(round(float(row["highPrice"]))),
            "low": int(round(float(row["lowPrice"]))),
            "volume": int(row.get("accumulatedTradingVolume") or 0),
        }
