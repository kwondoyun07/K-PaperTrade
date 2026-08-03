"""장 마감 후 일일 배치 — GitHub Actions 평일 16:30 KST 실행 진입점.

1) 일봉(전 종목)·투자자별 순매수·지수 → Turso krx_market (전부 upsert, 멱등)
2) 당일 전 종목 1분봉 → 일자별 parquet → GitHub Release(minute-YYYY-MM)
3) minute_prices 롤링 캐시 정리(10일 이전 행 삭제 — 5거래일 + 휴일 여유)

Turso 적재를 분봉보다 먼저 실행한다 — 소스가 서로 무관하므로 분봉(가장 오래
걸리고 깨지기 쉬움) 실패가 일봉·수급·지수 적재를 막지 않게.

업스트림 내구성 (2026-08-01 실측 기준):
- 휴장 판정: 네이버 분봉(005930) + FDR KS11 교차 확인 — 분봉이 없어도 KS11에
  데이터가 있으면 거래일(업스트림 이상 또는 제공범위 밖)로 구분한다
- 일봉: pykrx 벌크 1순위 → FDR KRX 스냅샷(당일만) → 방금 수집한 분봉에서 파생(최후).
  분봉 파생은 수집이 끝난 뒤에 시도하므로 순서상 마지막에 복구된다
- 지수: FDR(KS11/KQ11, 네이버 소스) 단독 — pykrx 지수 API는 빈 응답 확인됨
- 수급: pykrx만 가능 — 실패 시 경고 후 스킵(보조 데이터, 과거분 갭 허용)

휴장일이면 아무것도 하지 않고 0으로 종료. TURSO env 미설정이면 적재만 건너뜀.

사용:
  uv run python daily.py                          # 오늘(KST) 기준
  uv run python daily.py --date 2026-07-31
  uv run python daily.py --tickers 005930 --skip-upload   # 스모크
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import FinanceDataReader as fdr
import pandas as pd
from pykrx import stock as krx

from backfill import collect_minutes
from providers import make_provider
from store import upload_release
from turso import Turso
from universe import krx_listing, krx_stocks

KST = ZoneInfo("Asia/Seoul")
log = logging.getLogger(__name__)

INVESTORS = {"개인": "individual", "외국인": "foreigner", "기관합계": "institution"}
INDICES = (("KS11", "KOSPI"), ("KQ11", "KOSDAQ"))

DAILY_UPSERT = (
    "INSERT INTO daily_prices (ticker, date, open, high, low, close, volume) "
    "VALUES (?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(ticker, date) DO UPDATE SET open=excluded.open, high=excluded.high, "
    "low=excluded.low, close=excluded.close, volume=excluded.volume"
)


def upsert_stocks(db: Turso, stocks: list[dict], now: str) -> None:
    db.execute_batch(
        [
            (
                "INSERT INTO stocks (ticker, name, market, is_active, updated_at) "
                "VALUES (?, ?, ?, 1, ?) "
                "ON CONFLICT(ticker) DO UPDATE SET name=excluded.name, "
                "market=excluded.market, is_active=1, updated_at=excluded.updated_at",
                (s["ticker"], s["name"], s["market"], now),
            )
            for s in stocks
        ]
    )
    # 이번 목록에 없는 종목(상장폐지 등) 비활성화 — 재상장 시 다음 upsert가 복구
    db.execute("UPDATE stocks SET is_active=0 WHERE updated_at < ?", (now,))
    log.info("stocks upsert: %d행 (+미등재 종목 비활성화)", len(stocks))


def rows_from_parquet(date: str, out_dir: str | Path) -> list[tuple]:
    """방금 수집한 분봉에서 일봉을 파생 — pykrx·FDR이 모두 막혔을 때의 최후 수단.

    시가=첫 분봉 시가, 고/저=최대/최소, 종가=마지막 분봉 종가(15:30 종가단일가),
    거래량=합계. 장외·시간외 거래가 빠지므로 KRX 공식 일봉과 거래량이 미세하게
    다를 수 있다 — 그래도 일봉이 통째로 비는 것보다 낫다(분봉은 소급 수집 불가).
    """
    p = Path(out_dir) / f"minute-{date}.parquet"
    if not p.exists():
        return []
    df = pd.read_parquet(p).sort_values("ts")
    rows = []
    for tkr, g in df.groupby("ticker", sort=True):
        rows.append(
            (str(tkr), date, int(g["open"].iloc[0]), int(g["high"].max()),
             int(g["low"].min()), int(g["close"].iloc[-1]), int(g["volume"].sum()))
        )
    log.warning("분봉에서 일봉 파생: %d종목 (거래량은 장중 합계)", len(rows))
    return rows


def daily_price_rows(date: str, date8: str, today: str, listing, out_dir: str | Path) -> list[tuple]:
    """일봉 수집: pykrx 벌크 → FDR 스냅샷(당일만) → 분봉 파생(최후)."""
    try:
        df = krx.get_market_ohlcv(date8, market="ALL")
        if df.empty:
            raise ValueError("빈 응답")
        return [
            (str(t), date, int(r["시가"]), int(r["고가"]), int(r["저가"]),
             int(r["종가"]), int(r["거래량"]))
            for t, r in df.iterrows()
        ]
    except Exception as e:
        log.warning("pykrx 일봉 실패(%s) — 폴백 시도", e)
    if date == today:
        # 스냅샷은 최근 거래일 값이라 과거 일자엔 못 쓴다
        return [
            (str(r.Code), date, int(r.Open), int(r.High), int(r.Low), int(r.Close), int(r.Volume))
            for r in listing.itertuples()
        ]
    return rows_from_parquet(date, out_dir)


def load_flows(date8: str) -> dict[str, dict[str, int]]:
    """투자자별 순매수 거래대금(원) — 시장×투자자 6회 호출로 전 종목 커버.

    pykrx(KRX 포털) 전용 — 대체 무료 벌크 소스 없음. 실패 시 호출측에서 스킵.
    """
    rows: dict[str, dict[str, int]] = {}
    for market in ("KOSPI", "KOSDAQ"):
        for inv, col in INVESTORS.items():
            df = krx.get_market_net_purchases_of_equities_by_ticker(date8, date8, market, inv)
            if df.empty:
                raise ValueError(f"{market}/{inv} 빈 응답")
            for tkr, r in df.iterrows():
                rows.setdefault(str(tkr), {})[col] = int(r["순매수거래대금"])
    return rows


def upsert_flows(db: Turso, date: str, flows: dict[str, dict[str, int]]) -> None:
    stmts = [
        (
            "INSERT INTO investor_flows (ticker, date, individual, foreigner, institution) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(ticker, date) DO UPDATE SET individual=excluded.individual, "
            "foreigner=excluded.foreigner, institution=excluded.institution",
            (t, date, v.get("individual", 0), v.get("foreigner", 0), v.get("institution", 0)),
        )
        for t, v in flows.items()
    ]
    db.execute_batch(stmts)
    log.info("investor_flows upsert: %d행", len(stmts))


def upsert_indices(db: Turso, date: str) -> None:
    stmts = []
    for code, name in INDICES:
        df = fdr.DataReader(code, date, date)
        if df.empty:
            log.warning("지수 %s(%s) 데이터 없음", name, code)
            continue
        r = df.iloc[-1]
        stmts.append(
            (
                "INSERT INTO indices (code, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(code, date) DO UPDATE SET open=excluded.open, "
                "high=excluded.high, low=excluded.low, close=excluded.close, "
                "volume=excluded.volume",
                (name, date, float(r["Open"]), float(r["High"]), float(r["Low"]),
                 float(r["Close"]), int(r["Volume"])),
            )
        )
    if stmts:
        db.execute_batch(stmts)
    log.info("indices upsert: %d행", len(stmts))


def settle_accounts() -> None:
    """마감 후 ACCOUNT 미체결 주문을 정산한다.

    장중 마지막 판단(14:30)이 낸 주문은 그 시점엔 체결할 다음 분봉이 아직 없어
    PENDING으로 남는다 — 사용자가 화면(/quotes)을 열기 전까진 값이 안 잡힌다.
    하루 분봉이 다 모인 마감 후 여기서 채운다. 정산은 분봉이 고정돼 있어 언제
    돌든(collect가 지연돼도) 결과가 같다. 스냅샷보다 먼저 돌려 평가액이 오늘
    체결을 반영하게 한다. settleOwnerOrders는 멱등이라 중복 호출도 안전하다.
    """
    import os

    import httpx

    base = os.environ.get("APP_BASE_URL")
    secret = os.environ.get("CRON_SECRET")
    if not base or not secret:
        log.warning("APP_BASE_URL/CRON_SECRET 미설정 — ACCOUNT 정산 건너뜀")
        return
    try:
        r = httpx.post(
            base.rstrip("/") + "/api/v1/cron/settle",
            headers={"x-cron-secret": secret},
            timeout=60.0,
        )
        r.raise_for_status()
        d = r.json()
        log.info("ACCOUNT 정산: 체결 %s / 거부 %s", d.get("filled"), d.get("rejected"))
    except Exception as e:
        log.warning("ACCOUNT 정산 실패 — 스킵(다음 사이클 재시도): %s", e)


def snapshot_accounts(tdb: Turso, close_map: dict[str, int], date: str) -> None:
    """계좌별 평가액(현금+보유×당일 종가)을 portfolio_snapshots에 upsert (ts = date 15:30)."""
    accounts = tdb.query("SELECT id, cash FROM accounts")
    positions = tdb.query(
        "SELECT owner_id, ticker, qty, avg_price FROM positions WHERE owner_type = 'ACCOUNT' AND qty > 0"
    )
    by_acct: dict[int, list[dict]] = {}
    for p in positions:
        by_acct.setdefault(int(p["owner_id"]), []).append(p)
    ts = f"{date} 15:30"
    stmts = []
    for a in accounts:
        aid = int(a["id"])
        value = sum(
            int(p["qty"]) * int(close_map.get(str(p["ticker"]), p["avg_price"]))
            for p in by_acct.get(aid, [])
        )
        stmts.append(
            (
                "INSERT INTO portfolio_snapshots (owner_type, owner_id, ts, equity, cash) "
                "VALUES ('ACCOUNT', ?, ?, ?, ?) "
                "ON CONFLICT(owner_type, owner_id, ts) DO UPDATE SET equity=excluded.equity, cash=excluded.cash",
                (aid, ts, int(a["cash"]) + value, int(a["cash"])),
            )
        )
    if stmts:
        tdb.execute_batch(stmts)
    log.info("portfolio_snapshots: %d계좌 기록", len(stmts))


def update_ai_returns(tdb: Turso, mdb: Turso) -> None:
    """ai_decisions의 판단 이후 수익률(ret_d5/d20/d60, %)을 거래일 기준으로 채운다.

    기준가 = 판단일(이후 첫 거래일) 종가. n거래일 뒤 종가가 쌓이면 그때 채워진다.
    """
    from bisect import bisect_left

    pending = tdb.query(
        "SELECT id, ticker, ts, ret_d5, ret_d20, ret_d60 FROM ai_decisions "
        "WHERE ret_d5 IS NULL OR ret_d20 IS NULL OR ret_d60 IS NULL"
    )
    if not pending:
        return
    by_ticker: dict[str, list[dict]] = {}
    for d in pending:
        by_ticker.setdefault(str(d["ticker"]), []).append(d)
    updated = 0
    for ticker, items in by_ticker.items():
        closes = mdb.query(
            "SELECT date, close FROM daily_prices WHERE ticker = ? ORDER BY date", (ticker,)
        )
        dates = [str(r["date"]) for r in closes]
        for d in items:
            idx = bisect_left(dates, str(d["ts"])[:10])
            if idx >= len(dates):
                continue
            base = int(closes[idx]["close"])
            sets, args = [], []
            for n, col in ((5, "ret_d5"), (20, "ret_d20"), (60, "ret_d60")):
                if d[col] is None and idx + n < len(dates) and base > 0:
                    sets.append(f"{col} = ?")
                    args.append((int(closes[idx + n]["close"]) / base - 1) * 100)
            if sets:
                tdb.execute(f"UPDATE ai_decisions SET {', '.join(sets)} WHERE id = ?", (*args, int(d["id"])))
                updated += 1
    log.info("ai_decisions 수익률 갱신: %d건", updated)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청당 INFO 로그 억제
    p = argparse.ArgumentParser(description="장 마감 후 일일 수집 배치")
    p.add_argument("--date", help="YYYY-MM-DD (기본: 오늘 KST)")
    p.add_argument("--tickers", help="쉼표 구분 티커 — 스모크 테스트용")
    p.add_argument("--out", default="data/minute")
    p.add_argument("--provider", choices=["kiwoom", "naver"], help="기본: 키움(키 있으면)")
    p.add_argument("--skip-minute", action="store_true")
    p.add_argument("--skip-upload", action="store_true")
    a = p.parse_args()

    today = datetime.now(KST).strftime("%Y-%m-%d")
    date = a.date or today
    date8 = date.replace("-", "")
    if date > today:
        log.error("%s: 미래 날짜", date)
        return 1

    provider = make_provider(a.provider)
    log.info("프로바이더: %s", type(provider).__name__)
    skip_minute = a.skip_minute

    # 휴장·제공범위 판정: 분봉 프로브(005930) + KS11 교차 확인
    if not provider.get_minute_bars("005930", date):
        if fdr.DataReader("KS11", date, date).empty:
            log.info("%s 휴장일 — 종료", date)
            return 0
        if date == today:
            log.error("%s 거래일인데 분봉 없음 — 업스트림 이상, 실패 처리", date)
            return 1
        log.warning("%s 분봉 없음(프로바이더 제공범위 밖) — 분봉 스킵, 나머지 진행", date)
        skip_minute = True

    listing = krx_listing()
    stocks = krx_stocks(listing)
    if a.tickers:
        tickers = [t.strip() for t in a.tickers.split(",") if t.strip()]
    else:
        tickers = [s["ticker"] for s in stocks]
    rc = 0

    # 1) 일봉·수급·지수 → Turso
    db = Turso.from_env("KRX_MARKET")
    if db is None:
        log.warning("TURSO_KRX_MARKET_* env 미설정 — Turso 적재 건너뜀")
    else:
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        upsert_stocks(db, stocks, now)

        valid = {s["ticker"] for s in stocks}
        rows = [r for r in daily_price_rows(date, date8, today, listing, a.out) if r[0] in valid]
        if rows:
            db.execute_batch([(DAILY_UPSERT, r) for r in rows])
            log.info("daily_prices upsert: %d행", len(rows))
        else:
            # 아직 실패로 확정하지 않는다 — 분봉 수집 후 파생 폴백이 남아 있다
            log.warning("일봉 0행 — 분봉 수집 후 파생 재시도 예정")

        try:
            upsert_flows(db, date, load_flows(date8))
        except Exception as e:
            log.warning("수급 수집 실패 — 스킵 (보조 데이터): %s", e)

        upsert_indices(db, date)

        # 분봉 롤링 캐시 정리 — 최근 5거래일만 유지 (10일 = 휴일 여유 포함)
        cutoff = (datetime.now(KST) - timedelta(days=10)).strftime("%Y-%m-%d")
        db.execute("DELETE FROM minute_prices WHERE ts < ?", (cutoff,))
        log.info("minute_prices 캐시 정리: %s 이전 삭제", cutoff)

    # 2) 분봉 → parquet → Release
    if not skip_minute:
        files, failed = collect_minutes(provider, tickers, a.out, date)
        if failed and len(failed) > len(tickers) * 0.1:
            log.error("분봉 실패율 10%% 초과 (%d/%d) — 업로드 없이 실패 처리", len(failed), len(tickers))
            rc = 1
        elif files and not a.skip_upload:
            try:
                upload_release(files)
            except Exception as e:
                log.error("release 업로드 실패: %s", e)
                rc = 1

    # 3) 일봉 최후 폴백 — pykrx·FDR이 모두 막혔으면 방금 수집한 분봉에서 파생
    if db is not None:
        if not rows and not a.tickers:
            rows = [r for r in rows_from_parquet(date, a.out) if r[0] in valid]
            if rows:
                db.execute_batch([(DAILY_UPSERT, r) for r in rows])
                log.info("daily_prices upsert(분봉 파생): %d행", len(rows))
        if not rows:
            log.error("거래일인데 daily_prices 0행 — 실패 처리")
            rc = 1

        # 4) 계좌 스냅샷 + AI 판단 수익률 배치 (trading DB)
        tdb = Turso.from_env("TRADING")
        if tdb is None:
            log.warning("TURSO_TRADING_* env 미설정 — 스냅샷·AI 수익률 배치 건너뜀")
        else:
            settle_accounts()  # 스냅샷 전에 — 오늘 체결이 평가액에 반영되도록
            if rows:
                snapshot_accounts(tdb, {r[0]: r[5] for r in rows}, date)
            else:
                log.warning("일봉 0행 — 계좌 스냅샷 건너뜀")
            try:
                update_ai_returns(tdb, db)
            except Exception as e:
                log.warning("AI 수익률 배치 실패 — 스킵: %s", e)
    return rc


if __name__ == "__main__":
    sys.exit(main())
