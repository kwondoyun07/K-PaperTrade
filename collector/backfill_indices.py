"""과거 지수(KOSPI·KOSDAQ) 백필 → Turso krx_market.indices.

왜 필요한가: 일일 배치는 당일 1행씩만 쌓는다. 배치 가동 이전 구간이 통째로 비어
계좌 수익률을 KOSPI와 비교할 수 없다(알파 = 계좌 - 벤치마크).

FDR은 기간 조회를 한 번에 주므로 날짜 루프 없이 지수당 1회 호출이면 된다. upsert라 재실행 멱등.

사용:
  uv run --env-file ../.env python backfill_indices.py --since 2026-07-01
  uv run --env-file ../.env python backfill_indices.py --since 2026-07-01 --until 2026-08-14
"""

import argparse
import logging
import sys
from datetime import datetime

from daily import KST, upsert_indices
from turso import Turso

log = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(description="과거 지수 백필")
    p.add_argument("--since", required=True, help="YYYY-MM-DD")
    p.add_argument("--until", help="YYYY-MM-DD (기본: 오늘 KST)")
    a = p.parse_args()

    until = a.until or datetime.now(KST).strftime("%Y-%m-%d")
    db = Turso.from_env("KRX_MARKET")
    if db is None:
        log.error("TURSO_KRX_MARKET_* 미설정")
        return 1

    try:
        n = upsert_indices(db, a.since, until)
    except Exception as e:
        log.error("지수 백필 실패: %s", e)
        return 1
    log.info("백필 완료: %s~%s, indices %d행", a.since, until, n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
