"""Release의 과거 분봉 parquet에서 일봉을 파생해 Turso daily_prices에 적재.

왜 필요한가: 매일 배치는 당일 일봉만 쌓는다. 과거 분봉을 백필해도
daily_prices는 비어 있어 MA20·거래량비 같은 지표가 계산되지 않고,
AI 판단·가격제한폭 기준·포트폴리오 평가가 전부 부실해진다.

거래량은 장중 합계라 KRX 공식 일봉과 미세하게 다를 수 있다(장외 제외).
공식 일봉이 나중에 들어오면 upsert가 덮어쓴다.

사용:
  uv run --env-file ../.env python backfill_daily.py --since 2025-08 --until 2026-07
"""

import argparse
import io
import logging
import sys
from datetime import date

import httpx
import pandas as pd

from daily import DAILY_UPSERT
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
    df = pd.read_parquet(io.BytesIO(buf)).sort_values("ts")
    return [
        (str(t), date_str, int(g["open"].iloc[0]), int(g["high"].max()),
         int(g["low"].min()), int(g["close"].iloc[-1]), int(g["volume"].sum()))
        for t, g in df.groupby("ticker", sort=True)
    ]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Release 분봉 → daily_prices 파생 적재")
    p.add_argument("--since", required=True, help="YYYY-MM")
    p.add_argument("--until", required=True, help="YYYY-MM")
    a = p.parse_args()

    db = Turso.from_env("KRX_MARKET")
    if db is None:
        log.error("TURSO_KRX_MARKET_* 미설정")
        return 1

    client = httpx.Client(timeout=60.0, follow_redirects=True)
    total_rows = total_days = 0
    for tag in months(a.since, a.until):
        for asset in assets(client, f"minute-{tag}"):
            name = asset["name"]
            if not name.startswith("minute-") or not name.endswith(".parquet"):
                continue
            d = name[7:17]
            r = client.get(asset["browser_download_url"])
            if r.status_code != 200:
                log.warning("다운로드 실패 %s (%s)", name, r.status_code)
                continue
            rows = daily_rows(r.content, d)
            if not rows:
                continue
            db.execute_batch([(DAILY_UPSERT, x) for x in rows])
            total_rows += len(rows)
            total_days += 1
            if total_days % 20 == 0:
                log.info("%d일자 / %d행 (최근 %s)", total_days, total_rows, d)
    log.info("완료: %d일자, daily_prices %d행 upsert", total_days, total_rows)
    return 0 if total_days else 1


if __name__ == "__main__":
    sys.exit(main())
