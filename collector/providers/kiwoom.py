"""키움증권 REST API 프로바이더 (모의투자) — v1 주력 소스.

2026-08-02 실측으로 확정한 사항 (문서가 아니라 실제 호출 결과):
- 호스트: 모의투자 https://mockapi.kiwoom.com / 실전 https://api.kiwoom.com
  (키가 투자구분과 다르면 8030 오류로 거부되므로 실전 키 오용이 자동 차단된다)
- 토큰: POST /oauth2/token {grant_type, appkey, secretkey} → {token, expires_dt}
  유효기간 약 24시간
- 분봉: POST /api/dostk/chart, 헤더 api-id=ka10080,
  바디 {stk_cd, tic_scope, upd_stkpc_tp}
  응답 배열 stk_min_pole_chart_qry, **최신순 900건/페이지**
  행 키: cntr_tm(YYYYMMDDHHMMSS), open_pric, high_pric, low_pric, cur_prc(종가),
  trde_qty(분당 거래량), acc_trde_qty(누적)
  **가격에 +/- 부호가 붙어 오므로 반드시 제거**해야 한다
- 연속조회: 응답 헤더 cont-yn=Y + next-key를 다음 요청 헤더에 실어 과거로 이동.
  45페이지(40,500건)까지 확인했고 그 시점에도 cont-yn=Y — **최소 5개월 이상** 제공.
  네이버가 ~6거래일뿐인 것과 대비되며, 이게 교체의 핵심 이유다.
- **호출 제한: API ID당 초당 1회**(초과 시 HTTP 429, 1700 오류). 여유를 둬 1.1초 간격.

네이버 대조(2026-07-31 005930): 379봉 전부 OHLC 일치. 시가·종가 단일가 봉의
거래량만 미세하게 다르다(스냅샷 시점 차이로 추정).
"""

import logging
import os
import time
from datetime import datetime

import httpx

from .base import MinuteBar

log = logging.getLogger(__name__)

MOCK_HOST = "https://mockapi.kiwoom.com"
REAL_HOST = "https://api.kiwoom.com"
CHART_PATH = "/api/dostk/chart"
TR_MINUTE = "ka10080"


def _num(v: object) -> int:
    """'+262500' / '-200500' → 262500 / 200500 (부호는 전일 대비 방향 표시).

    결측(None·빈 문자열·비숫자)은 0으로. 필드가 비어 오는 경우가 있어 방어한다.
    """
    if v is None:
        return 0
    s = str(v).strip().replace("+", "").replace("-", "").replace(",", "")
    return int(s) if s.isdigit() else 0


class KiwoomProvider:
    """모의투자 서버 전용. 실전 호스트는 명시적으로 넘겨야 쓰인다(실거래 방지)."""

    def __init__(
        self,
        app_key: str | None = None,
        app_secret: str | None = None,
        host: str | None = None,
        req_interval: float = 1.1,  # 초당 1회 제한 + 여유
    ):
        self.app_key = app_key or os.environ.get("KIWOOM_APP_KEY", "")
        self.app_secret = app_secret or os.environ.get("KIWOOM_APP_SECRET", "")
        if not self.app_key or not self.app_secret:
            raise RuntimeError("KIWOOM_APP_KEY / KIWOOM_APP_SECRET 미설정")
        self.host = host or os.environ.get("KIWOOM_HOST", MOCK_HOST)
        if self.host == REAL_HOST:
            log.warning("키움 실전 호스트로 설정됨 — 이 프로젝트는 모의투자 전용이다")
        self.req_interval = req_interval
        self._client = httpx.Client(timeout=20.0)
        self._token = ""
        self._token_exp = 0.0
        self._last_req = 0.0

    def _throttle(self) -> None:
        wait = self.req_interval - (time.monotonic() - self._last_req)
        if wait > 0:
            time.sleep(wait)
        self._last_req = time.monotonic()

    def token(self) -> str:
        if self._token and time.time() < self._token_exp:
            return self._token
        r = self._client.post(
            f"{self.host}/oauth2/token",
            headers={"Content-Type": "application/json;charset=UTF-8"},
            json={
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "secretkey": self.app_secret,
            },
        )
        r.raise_for_status()
        j = r.json()
        tok = j.get("token")
        if not tok:
            raise RuntimeError(f"키움 토큰 발급 실패: {j.get('return_msg') or j}")
        self._token = tok
        # expires_dt 'YYYYMMDDHHMMSS' — 만료 5분 전에 갱신
        try:
            exp = datetime.strptime(str(j["expires_dt"]), "%Y%m%d%H%M%S").timestamp()
            self._token_exp = exp - 300
        except (KeyError, ValueError):
            self._token_exp = time.time() + 3600
        log.info("키움 토큰 발급 (만료 %s)", j.get("expires_dt", "?"))
        return self._token

    def _chart_page(self, ticker: str, cont_yn: str, next_key: str) -> tuple[list[dict], str, str]:
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.token()}",
            "api-id": TR_MINUTE,
        }
        if cont_yn == "Y":
            headers["cont-yn"] = "Y"
            headers["next-key"] = next_key

        for attempt in range(3):
            self._throttle()
            r = self._client.post(
                f"{self.host}{CHART_PATH}",
                headers=headers,
                json={"stk_cd": ticker, "tic_scope": "1", "upd_stkpc_tp": "1"},
            )
            if r.status_code == 429:
                # 유량 초과 — 간격을 늘려 재시도
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            j = r.json()
            if j.get("return_code") not in (0, "0", None):
                raise RuntimeError(f"{ticker}: {j.get('return_msg')}")
            return (
                j.get("stk_min_pole_chart_qry") or [],
                r.headers.get("cont-yn", "N"),
                r.headers.get("next-key", ""),
            )
        raise RuntimeError(f"{ticker}: 유량 초과로 재시도 실패")

    def get_minute_bars(
        self,
        ticker: str,
        date: str | None = None,
        since: str | None = None,
        until: str | None = None,
        max_pages: int = 400,
    ) -> list[MinuteBar]:
        """분봉 조회 (시각 오름차순).

        date  — 'YYYY-MM-DD' 해당 하루만
        since — 'YYYY-MM-DD' 그 날짜 **이후** 전부 (히스토리 백필용)
        until — 'YYYY-MM-DD' 그 날짜 **이하**만 (이미 확보한 구간과 겹치지 않게 자를 때)
        date·since 둘 다 없으면 첫 페이지(최근 900건)만.
        """
        target = (date or "").replace("-", "")
        floor = (since or date or "").replace("-", "")
        ceil = (until or "").replace("-", "")
        bars: list[MinuteBar] = []
        cont_yn, next_key = "N", ""

        for _ in range(max_pages):
            rows, cont_yn_next, next_key_next = self._chart_page(ticker, cont_yn, next_key)
            if not rows:
                break
            oldest = str(rows[-1].get("cntr_tm", ""))[:8]
            for x in rows:
                t = str(x.get("cntr_tm", ""))
                if len(t) < 12:
                    continue
                d8 = t[:8]
                if target and d8 != target:
                    continue
                if floor and d8 < floor:
                    continue
                if ceil and d8 > ceil:
                    continue
                ts = f"{t[0:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}"
                bars.append(
                    MinuteBar(
                        ticker,
                        ts,
                        _num(x.get("open_pric")),
                        _num(x.get("high_pric")),
                        _num(x.get("low_pric")),
                        _num(x.get("cur_prc")),
                        _num(x.get("trde_qty")),
                    )
                )
            # 목표 구간을 이미 지나쳤으면 중단 (최신순이므로 oldest가 기준 아래면 끝)
            if floor and oldest < floor:
                break
            if not floor:
                break
            if cont_yn_next != "Y" or not next_key_next:
                break
            cont_yn, next_key = "Y", next_key_next

        bars.sort(key=lambda b: b.ts)
        return bars

    def get_daily_bars(self, ticker: str, start: str, end: str) -> list[dict]:
        raise NotImplementedError("일봉·수급은 pykrx/FDR 경로 사용 (daily.py 참고)")

    def get_quote(self, ticker: str) -> dict:
        bars = self.get_minute_bars(ticker)
        if not bars:
            raise ValueError(f"{ticker}: 분봉 없음")
        last = bars[-1]
        return {"ticker": ticker, "ts": last.ts, "price": last.close, "volume": last.volume}
