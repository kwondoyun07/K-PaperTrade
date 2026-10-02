"""Release의 과거 분봉 parquet에서 일봉을 파생해 Turso daily_prices에 적재.

왜 필요한가: 매일 배치는 당일 일봉만 쌓는다. 과거 분봉을 백필해도
daily_prices는 비어 있어 MA20·거래량비 같은 지표가 계산되지 않고,
AI 판단·가격제한폭 기준·포트폴리오 평가가 전부 부실해진다.

파생 규칙은 daily.py와 같다(daily_from_bars): 정규장 09:00~15:40 봉만 쓰고 거래량도
정규장분이다. ETF는 넣지 않는다 — 9/16 분봉 파일엔 ETF 1,160종목이 섞여 있다.

사용:
  uv run --env-file ../.env python backfill_daily.py --since 2025-08 --until 2026-07
  uv run --env-file ../.env python backfill_daily.py --since 2026-08 --until 2026-10 \
      --dates 2026-08-27,2026-08-31          # 그 달 중 지정한 날짜만 다시 쓴다
"""

import argparse
import io
import logging
import sys

import httpx
import pandas as pd

from daily import DAILY_UPSERT, daily_from_bars
from turso import Turso

log = logging.getLogger(__name__)
REPO = "kwondoyun07/K-PaperTrade"


def months(since: str, until: str) -> list[str]:
    y, m = map(int, since.split("-"))
    ey, em = map(int, until.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def assets(client: httpx.Client, tag: str) -> list[dict]:
    r = client.get(f"https://api.github.com/repos/{REPO}/releases/tags/{tag}")
    if r.status_code != 200:
        log.warning("릴리스 없음: %s", tag)
        return []
    return r.json().get("assets", [])


def daily_rows(buf: bytes, date_str: str) -> list[tuple]:
    return daily_from_bars(pd.read_parquet(io.BytesIO(buf)), date_str)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Release 분봉 → daily_prices 파생 적재")
    p.add_argument("--since", required=True, help="YYYY-MM")
    p.add_argument("--until", required=True, help="YYYY-MM")
    p.add_argument("--dates", help="쉼표 구분 YYYY-MM-DD — 지정하면 그 날짜만")
    a = p.parse_args()

    db = Turso.from_env("KRX_MARKET")
    if db is None:
        log.error("TURSO_KRX_MARKET_* 미설정")
        return 1
    only = {d.strip() for d in (a.dates or "").split(",") if d.strip()}
    # is_active는 보지 않는다 — 그날 거래됐지만 지금은 상장폐지된 종목의 과거 일봉도 맞는 값이다.
    valid = {str(r["ticker"]) for r in db.query("SELECT ticker FROM stocks WHERE market != 'ETF'")}

    client = httpx.Client(timeout=60.0, follow_redirects=True)
    total_rows = total_days = 0
    for tag in months(a.since, a.until):
        for asset in assets(client, f"minute-{tag}"):
            name = asset["name"]
            if not name.startswith("minute-") or not name.endswith(".parquet"):
                continue
            d = name[7:17]
            if only and d not in only:
                continue
            r = client.get(asset["browser_download_url"])
            if r.status_code != 200:
                log.warning("다운로드 실패 %s (%s)", name, r.status_code)
                continue
            rows = [x for x in daily_rows(r.content, d) if x[0] in valid]
            if not rows:
                continue
            db.execute_batch([(DAILY_UPSERT, x) for x in rows])
            total_rows += len(rows)
            total_days += 1
            log.info("%s: %d행 (누적 %d일자 / %d행)", d, len(rows), total_days, total_rows)
    log.info("완료: %d일자, daily_prices %d행 upsert", total_days, total_rows)
    return 0 if total_days else 1


if __name__ == "__main__":
    sys.exit(main())
