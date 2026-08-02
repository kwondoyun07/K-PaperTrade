"""전 종목 1분봉 백필 — 네이버가 제공하는 최근 ~6거래일 전부를 parquet로 적재.

사용 (collector/ 디렉토리에서):
  uv run python backfill.py                        # 전 종목 → data/minute/
  uv run python backfill.py --tickers 005930,000660
  uv run python backfill.py --upload               # GitHub Release 업로드까지

전 종목 1요청/종목(멀티데이 범위), 기본 0.5초 간격 → 약 2,700요청 / 25분.
"""

import argparse
import logging
import sys
from pathlib import Path

from providers.base import DataProvider
from store import MinuteParquetStore, upload_release
from universe import krx_stocks, watchlist

log = logging.getLogger(__name__)


def collect_minutes(
    provider: DataProvider,
    tickers: list[str],
    out_dir: str | Path,
    date: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> tuple[list[Path], list[str]]:
    """티커들의 분봉을 수집해 일자별 parquet로 저장. (파일 목록, 실패 티커) 반환.

    since·until은 키움 프로바이더에서만 의미가 있다(네이버는 ~6거래일만 제공).
    """
    store = MinuteParquetStore(out_dir)
    failed: list[str] = []
    ordered = sorted(tickers)
    streak = 0
    for i, t in enumerate(ordered, 1):
        try:
            kwargs = {}
            if since:
                kwargs["since"] = since
            if until:
                kwargs["until"] = until
            store.add(provider.get_minute_bars(t, date, **kwargs))
            streak = 0
        except Exception as e:
            failed.append(t)
            streak += 1
            log.warning("%s 수집 실패: %s", t, e)
            if streak >= 20:
                # 연속 실패 = 차단·전면 장애 신호. 재시도 폭주로 잡 타임아웃을
                # 채우는 대신 중단하고, 남은 종목을 실패로 집계해 게이트를 발동시킨다.
                rest = ordered[i:]
                failed.extend(rest)
                log.error("연속 %d회 실패 — 업스트림 이상 추정, 남은 %d종목 수집 중단", streak, len(rest))
                break
        if i % 100 == 0:
            log.info("%d/%d 종목, %d행", i, len(tickers), store.rows)
    files = store.close()
    log.info(
        "수집 완료: %d종목 (실패 %d), %d행 → %s",
        len(tickers), len(failed), store.rows, ", ".join(f.name for f in files) or "(파일 없음)",
    )
    if failed:
        head = ",".join(failed[:50])
        log.warning("실패 종목: %s%s", head, "..." if len(failed) > 50 else "")
    return files, failed


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청당 INFO 로그 억제
    p = argparse.ArgumentParser(description="KRX 전 종목 분봉 백필")
    p.add_argument("--tickers", help="쉼표 구분 티커 (기본: KRX 전 종목)")
    p.add_argument("--date", help="YYYY-MM-DD — 지정 시 해당 거래일만")
    p.add_argument("--since", help="YYYY-MM-DD — 그 날짜 이후 전부 (키움만 가능)")
    p.add_argument("--until", help="YYYY-MM-DD — 그 날짜 이하만 (기존 확보 구간과 겹침 방지)")
    p.add_argument("--top", type=int, help="시총 상위 N종목만 (과거 백필용)")
    p.add_argument("--provider", choices=["kiwoom", "naver"], help="기본: 키움(키 있으면)")
    p.add_argument("--out", default="data/minute")
    p.add_argument("--upload", action="store_true", help="GitHub Release 업로드")
    a = p.parse_args()

    from providers import make_provider

    if a.tickers:
        tickers = [t.strip() for t in a.tickers.split(",") if t.strip()]
    elif a.top:
        tickers = watchlist(a.top)
        log.info("시총 상위 %d종목", len(tickers))
    else:
        tickers = [s["ticker"] for s in krx_stocks()]
    provider = make_provider(a.provider)
    log.info("프로바이더: %s", type(provider).__name__)
    files, failed = collect_minutes(provider, tickers, a.out, a.date, a.since, a.until)
    # 실패율 10% 초과면 차단 등 비정상 신호 — 불완전 parquet 업로드 전에 중단
    if failed and len(failed) > len(tickers) * 0.1:
        log.error("실패율 10%% 초과 (%d/%d) — 업로드 없이 중단", len(failed), len(tickers))
        return 1
    if a.date and not files:
        log.error("%s: 수집 0행 — 휴장이거나 네이버 제공범위(~6거래일) 밖", a.date)
        return 1
    if a.upload and files:
        upload_release(files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
