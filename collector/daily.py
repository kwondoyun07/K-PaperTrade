"""장 마감 후 일일 배치 — GitHub Actions 평일 16:30 KST 실행 진입점.

1) 수급·지수·코어 ETF 일봉 → Turso krx_market (전부 upsert, 멱등)
2) 당일 전 종목 1분봉 → 일자별 parquet → GitHub Release(minute-YYYY-MM)
3) 그 분봉의 정규장(09:00~15:40) 봉에서 일봉을 파생 → daily_prices
4) 키움 잔고 동기화·계좌 스냅샷·AI 판단 채점

일봉 소스는 **자체 분봉 하나뿐**이다(docs/data-pipeline.md). 예전엔 pykrx → FDR 상장목록
스냅샷 → 분봉 순이었는데, pykrx가 죽은 뒤로는 '수집 시각의 캐시 스냅샷'이 그대로 종가로
들어갔다 — 16:30 수집은 정오 값, 밤 수집은 시간외 값이었다(2026-10 진단).

- 휴장 판정: 분봉 프로브(005930)가 비면 지수 날짜(FDR → 네이버)로 묻는다.
- 지수: FDR(KS11/KQ11) → 네이버 폴백. DB에는 code='KOSPI'/'KOSDAQ'(웹 조회 키).
  실패는 rc=1 — 벤치마크 필수 데이터다. 과거분은 backfill_indices.py
- 수급: 네이버 종목별(시총 상위 30) — 실패 시 경고 후 스킵(보조 데이터)

기준일은 '실행 시각 − 9시간'의 날짜다 — 밀려서 자정을 넘긴 실행이 다음 날을 수집하지 않게.
휴장일이면 아무것도 하지 않고 0으로 종료. TURSO env 미설정이면 적재만 건너뜀.

사용:
  uv run python daily.py                          # 직전 장 마감일 기준
  uv run python daily.py --date 2026-07-31        # 과거일: 분봉·지수만(스냅샷·키움 동기화 없음)
  uv run python daily.py --tickers 005930 --skip-upload   # 스모크(일봉은 안 쓴다)
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import FinanceDataReader as fdr
import pandas as pd

from backfill import collect_minutes
from providers import make_provider
from store import upload_release
from turso import Turso
from universe import CORE_TICKER, etf_stocks, holiday_verdict, krx_listing, krx_stocks, watchlist

KST = ZoneInfo("Asia/Seoul")
log = logging.getLogger(__name__)

INDICES = (("KS11", "KOSPI"), ("KQ11", "KOSDAQ"))
# 채점의 거래일 달력으로 쓰는 종목. 거래정지가 사실상 없고 일봉 이력이 가장 길다.
CALENDAR_TICKER = "005930"

DAILY_UPSERT = (
    "INSERT INTO daily_prices (ticker, date, open, high, low, close, volume) "
    "VALUES (?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(ticker, date) DO UPDATE SET open=excluded.open, high=excluded.high, "
    "low=excluded.low, close=excluded.close, volume=excluded.volume"
)

INDEX_UPSERT = (
    "INSERT INTO indices (code, date, open, high, low, close, volume) "
    "VALUES (?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(code, date) DO UPDATE SET open=excluded.open, high=excluded.high, "
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


# 정규장 창. 2026-09-14부터 분봉에 16:00~19:59(시간외) 봉이 있어, 자르지 않으면 20:00 가격이
# '종가'가 된다. 15:30이 아니라 15:40인 이유: 종가가 15:32·15:35 봉에서 정해지는 종목이 하루
# 3~12개 있다. 이 창의 파생값은 금융위 확정 시세와 전 종목 시·고·저·종이 일치한다(9/30 2,571종목).
SESSION = ("09:00", "15:40")


def daily_from_bars(df: pd.DataFrame, date: str) -> list[tuple]:
    """분봉(ticker, ts, open, high, low, close, volume) → 일봉 upsert 인자. 순수 함수.

    시가=첫 봉 시가, 고/저=최대/최소, 종가=정규장 마지막 봉 종가, 거래량=정규장 합계.
    거래량은 시간외분이 빠져 공식 거래량의 약 0.97배다. 그날 정규장 봉이 없는 종목(거래정지
    등)은 행이 없다.
    """
    hm = df["ts"].str[11:16]
    df = df[(hm >= SESSION[0]) & (hm <= SESSION[1])].sort_values("ts")
    return [
        (str(t), date, int(g["open"].iloc[0]), int(g["high"].max()),
         int(g["low"].min()), int(g["close"].iloc[-1]), int(g["volume"].sum()))
        for t, g in df.groupby("ticker", sort=True)
    ]


def rows_from_parquet(date: str, out_dir: str | Path) -> list[tuple]:
    """방금 수집한 그날 분봉 parquet에서 일봉을 파생한다. 파일이 없으면 빈 리스트."""
    p = Path(out_dir) / f"minute-{date}.parquet"
    if not p.exists():
        return []
    return daily_from_bars(pd.read_parquet(p), date)


def business_date(now: datetime) -> str:
    """수집 기준일 = 실행 시각 − 9시간의 날짜. 16:30 실행은 당일, 밀려서 자정을 넘긴 실행은 전일.

    그냥 오늘 날짜를 쓰면 00:47에 도착한 전일분 실행이 '오늘'을 수집하려다 분봉이 없어
    휴장으로 판정하고 초록으로 끝난다 — 8/28·9/1에 그렇게 거래일이 통째로 빠졌다.
    """
    return (now - timedelta(hours=9)).strftime("%Y-%m-%d")


def after_close(started: datetime, date: str) -> bool:
    """date의 장이 끝난 뒤에 시작한 실행인가. 일봉·스냅샷·체결 확정은 이때만 쓴다.

    장중에 돌리면 그 시각까지의 값이 '종가'로 들어가고(수집은 50분 넘게 걸려 종목마다 잘린
    시각도 다르다), 아직 체결 전인 주문이 평단 추정으로 굳는다.
    """
    return date < started.strftime("%Y-%m-%d") or started.strftime("%H:%M") > SESSION[1]


def load_flows(tickers: list[str]) -> dict[str, list[dict]]:
    """종목별 투자자 순매수 **수량**(주) — 네이버가 종목당 최근 10거래일을 준다.

    원래 pykrx(KRX 포털)로 시장×투자자 6회에 전 종목을 받았는데, KRX가 2026-09부터
    계정 인증을 요구해 막혔다(KRX_ID/KRX_PW 환경변수 요구). investor_flows는 그 탓에
    한 번도 채워진 적이 없다 — 실측 0행이었다.

    네이버는 종목별 호출이라 전 종목(2,700여 개)은 비현실적이다. 수급은 AI 판단이
    쓰지 않고 종목 상세 화면의 카드 하나에만 쓰이므로 시총 상위로 좁힌다.

    단위가 금액에서 수량으로 바뀐다 — 화면 라벨도 '(주)'로 맞췄다.
    """
    from providers.naver import NaverProvider

    p = NaverProvider()
    out: dict[str, list[dict]] = {}
    for t in tickers:
        try:
            rows = p.get_investor_flows(t)
        except Exception as e:  # 한 종목 실패가 전체를 막지 않는다(보조 데이터)
            log.warning("%s 수급 조회 실패: %s", t, str(e)[:60])
            continue
        if rows:
            out[t] = rows
    return out


def upsert_flows(db: Turso, flows: dict[str, list[dict]]) -> None:
    """종목당 여러 날짜를 한 번에 넣는다 — 네이버가 10거래일치를 주므로 결손도 같이 메워진다."""
    stmts = [
        (
            "INSERT INTO investor_flows (ticker, date, individual, foreigner, institution) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(ticker, date) DO UPDATE SET individual=excluded.individual, "
            "foreigner=excluded.foreigner, institution=excluded.institution",
            (t, r["date"], r["individual"], r["foreigner"], r["institution"]),
        )
        for t, rows in flows.items()
        for r in rows
    ]
    if not stmts:
        log.warning("수급 0행 — 적재 건너뜀")
        return
    db.execute_batch(stmts)
    log.info("investor_flows upsert: %d행 (%d종목)", len(stmts), len(flows))


def _px(v: object, close: float) -> float:
    """0·NaN·결측이면 종가로 대체. `float(v) or close`는 NaN을 못 막는다(bool(nan)=True)
    — 스키마가 NOT NULL인데 NaN이 그대로 들어갔다."""
    try:
        x = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return close
    return x if x and x == x else close


def etf_daily_rows(ticker: str, start: str, end: str) -> list[tuple]:
    """ETF 하나의 일봉(FDR 종목 조회) → daily_prices upsert 인자. 코어 ETF 전용.

    시/고/저가가 비면 종가로 채운다(벤치마크·평가는 종가만 쓴다).
    """
    rows = []
    for ts, r in fdr.DataReader(ticker, start, end).iterrows():
        c = r.get("Close")
        if c is None or c != c or not c:
            continue

        def px(v):
            return int(v) if v is not None and v == v and v else int(c)

        vol = r.get("Volume")
        rows.append((ticker, str(ts)[:10], px(r.get("Open")), px(r.get("High")), px(r.get("Low")),
                     int(c), 0 if vol is None or vol != vol else int(vol)))
    return rows


def index_rows(df: pd.DataFrame, name: str) -> list[tuple]:
    """FDR 지수 OHLCV → indices upsert 인자. 종가 결측/0인 행은 버린다.

    시/고/저가 0·NaN인 과거 행이 섞여 있다(FDR 네이버 소스) — 종가로 대체한다.
    벤치마크 계산은 종가만 쓰므로 행을 통째로 버리는 것보다 낫다.
    """
    rows = []
    for ts, r in df.iterrows():
        close = float(r["Close"])
        if not close or close != close:  # NaN
            continue
        vol = r.get("Volume")
        rows.append(
            (
                name,
                str(ts)[:10],
                _px(r["Open"], close),
                _px(r["High"], close),
                _px(r["Low"], close),
                close,
                0 if vol is None or vol != vol else int(vol),
            )
        )
    return rows


def upsert_indices(db: Turso, start: str, end: str | None = None) -> int:
    """지수(KOSPI·KOSDAQ)를 [start, end] 구간으로 적재. **하나라도 결손이면 예외**.

    벤치마크 필수 데이터라 조용히 넘어가면 알파를 못 잰다 — 호출측이 실패로 다룬다.
    KOSPI만 들어오고 KOSDAQ이 비어도 실패다: 코스닥 종목의 벤치마크가 통째로 없는데
    rc=0이면 CI가 초록이라 아무도 모른다. 받아온 쪽은 그래도 쓰고(멱등) 나서 던진다.
    """
    end = end or start
    stmts: list[tuple] = []
    errors = []
    for code, name in INDICES:
        rows: list[tuple] = []
        why = "FDR 빈 응답"
        try:
            rows = index_rows(fdr.DataReader(code, start, end), name)
        except Exception as e:
            why = f"FDR 조회 실패: {e}"
            log.warning("%s(%s) %s — 네이버 폴백", name, code, why[:80])
        if not rows:
            # FDR이 2026-09-18부터 지수를 안 줘서 collect가 매일 실패했다. 벤치마크를
            # 소스 하나에 걸어두면 통째로 멎는다 — 네이버로 한 번 더 시도한다.
            try:
                from providers.naver import NaverProvider

                span = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
                got = NaverProvider().get_index_prices(name, size=max(10, span + 5))
                rows = [r for r in got if start <= r[1] <= end]
                if rows:
                    log.info("지수 %s: 네이버 폴백 %d행", name, len(rows))
            except Exception as e:
                why += f" / 네이버 폴백 실패: {e}"
        if not rows:
            # 두 소스의 실패 사유를 함께 남긴다 — 어느 쪽이 죽었는지 로그만 봐도 알게.
            errors.append(f"{name}({code}) 데이터 없음 ({why})")
            continue
        log.info("지수 %s: %d행 (%s~%s)", name, len(rows), rows[0][1], rows[-1][1])
        stmts += [(INDEX_UPSERT, r) for r in rows]
    if stmts:
        db.execute_batch(stmts)
        log.info("indices upsert: %d행", len(stmts))
    if errors:
        raise RuntimeError(("지수 0행 — " if not stmts else "지수 일부 결손 — ") + "; ".join(errors))
    return len(stmts)


def snapshot_accounts(tdb: Turso, close_map: dict[str, int], date: str) -> None:
    """계좌별 평가액을 portfolio_snapshots에 upsert (ts = date 15:30).

    총자산은 키움 추정예탁자산(est_asset)을 우선 쓴다 — ETF는 일봉을 수집하지 않아
    close_map에 없고, 그러면 매입가로 굳어 시세 변동이 곡선에 안 잡힌다(153130은
    포트의 25%였다). 없으면 현금+보유×당일 종가로 계산 폴백.
    """
    accounts = tdb.query("SELECT id, cash, est_asset FROM accounts")
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
        equity = int(a["est_asset"]) if a["est_asset"] else int(a["cash"]) + value
        stmts.append(
            (
                "INSERT INTO portfolio_snapshots (owner_type, owner_id, ts, equity, cash) "
                "VALUES ('ACCOUNT', ?, ?, ?, ?) "
                "ON CONFLICT(owner_type, owner_id, ts) DO UPDATE SET equity=excluded.equity, cash=excluded.cash",
                (aid, ts, equity, int(a["cash"])),
            )
        )
    if stmts:
        tdb.execute_batch(stmts)
    log.info("portfolio_snapshots: %d계좌 기록", len(stmts))


def _intraday(ts: str) -> bool:
    """판단 시각이 장중(09:00~15:29 KST)인가. ts는 'YYYY-MM-DD HH:MM'."""
    hm = ts[11:16]
    return "09:00" <= hm < "15:30"


def update_ai_returns(tdb: Turso, mdb: Turso) -> None:
    """ai_decisions의 판단 이후 수익률(ret_d5/d20/d60, %)을 거래일 기준으로 채운다.

    기준가 = 판단 시점에 AI가 본 가격(decision_price, decide.py가 기록) → ret_basis='decision'.
    없으면(005 마이그레이션 이전 과거분) 판단일 종가로 폴백하고 ret_basis='close'로 표시한다.
    마감 후(15:30~09:00)에 난 판단은 ret_basis='postclose' — 기준가가 사실상 당일 종가이고
    그날 움직임을 전부 본 뒤 내린 것이라 장중 판단과 같은 자로 잴 수 없다. GitHub schedule이
    10~11시간씩 밀리던 동안 이 경로로 115건이 쌓였다(decide.py가 이제 원천 차단한다).

    판단일 종가를 기준가로 쓰면 안 되는 이유: 같은 날·같은 종목의 BUY와 HOLD가 글자
    그대로 같은 값을 받아 판단이 아니라 종목·날짜를 재게 되고, AI는 그날 오르는 종목을
    사므로 이미 오른 종가가 진입가가 돼 BUY에만 핸디캡이 실린다(실측 3.91pp 역전).
    ret_basis='close' 행은 소급 복구가 불가능하니 분석에서 걸러 써야 한다.

    체결가(executions.price)는 일부러 안 쓴다 — 실제 체결가가 맞지만 주문이 난 판단에만
    있어서, HOLD와 SELL은 기준가가 없어진다. 판단 시점 가격이어야 셋을 같은 자로 잰다.

    n거래일 뒤는 **시장 달력**으로 센다(CALENDAR_TICKER의 일봉 날짜). 종목별 행 번호로 세면
    그 종목에 빠진 날이 있을 때 조용히 하루씩 밀린다 — 9/8~9/10 일봉이 비었을 때 9/1 판단
    30건이 5일 뒤가 아니라 8일 뒤 종가로 채점됐다. 목표일에 그 종목 종가가 없으면 쓰지 않는다.

    값이 비었을 때만 쓰는 게 아니라 **계산값이 저장값과 다르면 다시 쓴다**(60일 값이 찰 때까지).
    예전엔 한 번 쓰면 굳어서, 틀린 일봉으로 채점된 값이 일봉을 고쳐도 남았다(신뢰 표본의 61%).
    ret_basis='junk'(유니버스 결함으로 판단된 엉뚱한 종목)는 건드리지 않는다.
    """
    from bisect import bisect_left

    pending = tdb.query(
        "SELECT id, ticker, ts, decision_price, ret_basis, ret_d5, ret_d20, ret_d60 FROM ai_decisions "
        "WHERE ret_d5 IS NULL OR ret_d20 IS NULL OR ret_d60 IS NULL"
    )
    if not pending:
        return
    cal = [str(r["date"]) for r in mdb.query(
        "SELECT date FROM daily_prices WHERE ticker = ? ORDER BY date", (CALENDAR_TICKER,))]
    by_ticker: dict[str, list[dict]] = {}
    for d in pending:
        if d.get("ret_basis") != "junk":
            by_ticker.setdefault(str(d["ticker"]), []).append(d)
    stmts: list[tuple] = []
    fallback = late = 0
    for ticker, items in by_ticker.items():
        px = {str(r["date"]): float(r["close"]) for r in mdb.query(
            "SELECT date, close FROM daily_prices WHERE ticker = ? ORDER BY date", (ticker,))}
        for d in items:
            dday = str(d["ts"])[:10]
            idx = bisect_left(cal, dday)
            if idx >= len(cal):
                continue
            base = float(d["decision_price"] or 0)
            basis = "decision"
            if base <= 0:
                base, basis = px.get(cal[idx], 0.0), "close"
            elif cal[idx] != dday:
                # 판단일이 거래일이 아니다(휴장). 그날 시장 반응이 없어 기준일이 어긋나고,
                # bisect가 다음 거래일을 집어 수익률이 하루씩 밀린다. 측정에서 뺀다.
                basis = "holiday"
            elif not _intraday(str(d["ts"])):
                basis = "postclose"  # 기준가는 있지만 장 끝나고 본 값이다
            sets, args = ["ret_basis = ?"], [basis]
            for n, col in ((5, "ret_d5"), (20, "ret_d20"), (60, "ret_d60")):
                close = px.get(cal[idx + n]) if idx + n < len(cal) else None
                if not close or base <= 0:
                    continue
                new = (close / base - 1) * 100
                if d[col] is None or abs(new - float(d[col])) > 1e-9:
                    sets.append(f"{col} = ?")
                    args.append(new)
            # 이미 붙은 라벨이 틀렸으면 새 값 없이도 고쳐 쓴다. 예전엔 새 수익률이 채워질 때만
            # 써서, 5·20일 값이 있는 판단은 60일 값이 나오는 두 달 뒤까지 라벨이 안 바뀌었다
            # (8/17 휴장일 30건이 'decision'으로 남았다). 단 **라벨이 없던 행엔 붙이지 않는다** —
            # 점수 없는 행에 'decision'이 붙으면 신뢰 표본으로 세어진다(실제로 203건이 붙어
            # 17거래일이 22거래일로 부풀었다). 첫 점수가 들어올 때 같이 쓰면 된다.
            relabel = d.get("ret_basis") is not None and d.get("ret_basis") != basis
            if len(sets) > 1 or relabel:
                stmts.append((f"UPDATE ai_decisions SET {', '.join(sets)} WHERE id = ?", (*args, int(d["id"]))))
                fallback += basis == "close"
                late += basis in ("postclose", "holiday")
    if stmts:
        tdb.execute_batch(stmts)
    log.info("ai_decisions 수익률 갱신: %d건 (기준가 폴백 %d건, 마감 후·휴장일 판단 %d건 — 측정에서 제외)",
             len(stmts), fallback, late)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청당 INFO 로그 억제
    p = argparse.ArgumentParser(description="장 마감 후 일일 수집 배치")
    p.add_argument("--date", help="YYYY-MM-DD (기본: 직전 장 마감일 = 실행 시각 − 9시간의 날짜)")
    p.add_argument("--tickers", help="쉼표 구분 티커 — 스모크 테스트용(일봉은 쓰지 않는다)")
    p.add_argument("--out", default="data/minute")
    p.add_argument("--provider", choices=["kiwoom", "naver"], help="기본: 키움(키 있으면)")
    p.add_argument("--skip-minute", action="store_true", help="분봉 수집 생략 — 일봉도 쓰지 않는다")
    p.add_argument("--skip-upload", action="store_true")
    a = p.parse_args()

    started = datetime.now(KST)
    today = business_date(started)
    date = a.date or today
    if date > today:
        log.error("%s: 미래 날짜", date)
        return 1
    closed = after_close(started, date)

    provider = make_provider(a.provider)
    log.info("프로바이더: %s", type(provider).__name__)
    skip_minute = a.skip_minute
    rc = 0

    # 휴장·제공범위 판정: 분봉 프로브(005930)가 비면 지수 날짜로 묻는다.
    # 요일로 판정하지 않는 이유: 공휴일도 평일이라 매 명절마다 CI가 빨개진다.
    if not provider.get_minute_bars("005930", date):
        skip_minute = True
        verdict = holiday_verdict(date)
        if verdict == "holiday":
            log.info("%s 휴장일 — 종료", date)
            return 0
        if verdict is None:
            # 휴장인지 소스 동시 장애인지 구분이 안 된다. 휴장으로 넘기면 수급·지수·스냅샷이
            # 전부 스킵되고 rc=0이라 아무도 모른다.
            log.error("%s 휴장 판정 불가(분봉·지수 동시 결손) — 실패 처리", date)
            return 1
        if date == today:
            log.error("%s 거래일인데 분봉 없음 — 업스트림 이상, 실패 처리", date)
            return 1
        log.warning("%s 분봉 없음(프로바이더 제공범위 밖) — 분봉·일봉 스킵, 나머지 진행", date)

    # 상장목록이 죽어도 수집은 계속한다 — 9/8~9/10엔 이 호출 하나로 collect가
    # 사흘 내리 실패해 일봉·지수·자산 스냅샷이 통째로 비었다. 이름 갱신만 건너뛰고
    # 종목 목록은 DB에서 읽는다(전날까지 쌓인 stocks로 충분하다).
    db = Turso.from_env("KRX_MARKET")
    try:
        listing = krx_listing()
        stocks = krx_stocks(listing)
    except Exception as e:
        log.warning("KRX 상장목록 조회 실패(%s) — DB stocks로 폴백(이름 갱신 생략)", str(e)[:80])
        listing, stocks = None, []
        if db is not None:
            # ETF는 뺀다. stocks에 ETF 1,100여 개가 들어 있는 건 화면에 이름을 띄우려는
            # 것일 뿐 수집 대상이 아니다(universe.etf_stocks 주석). 빠뜨렸더니 9/16 폴백
            # 실행이 ETF 1,160개까지 분봉을 받아 일봉이 3,808행으로 부풀고 수집이
            # 54분 → 75분으로 늘었다 — 키움 초당 1회 제한 탓이다.
            stocks = [{"ticker": str(r["ticker"]), "name": str(r["name"]), "market": str(r["market"])}
                      for r in db.query("SELECT ticker, name, market FROM stocks "
                                        "WHERE is_active = 1 AND market != 'ETF'")]
            log.info("DB stocks 폴백: %d종목", len(stocks))
    if a.tickers:
        tickers = [t.strip() for t in a.tickers.split(",") if t.strip()]
    else:
        # 코어 ETF는 분봉도 받는다 — 계좌의 70%인데 분봉이 없으면 체결가를 나중에 대조할
        # 방법이 없다. 일봉은 아래 etf_daily_rows가 계속 맡는다(valid에는 넣지 않는다).
        tickers = [s["ticker"] for s in stocks] + [CORE_TICKER]
    valid = {s["ticker"] for s in stocks}
    rows: list[tuple] = []

    # 1) 수급·지수·코어 ETF 일봉 → Turso
    if db is None:
        log.warning("TURSO_KRX_MARKET_* env 미설정 — Turso 적재 건너뜀")
    else:
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        # ETF 이름도 같이 넣는다 — 화면에 코드만 뜨는 걸 막기 위한 이름 소스일 뿐,
        # 수집 유니버스(tickers)에는 넣지 않는다.
        # listing이 없으면(폴백 경로) stocks는 DB에서 읽은 것이라 되쓸 필요가 없다.
        if listing is not None:
            upsert_stocks(db, stocks + etf_stocks(), now)

        # 코어 ETF 일봉은 종목 조회로 받는다 — ETF 제외 규칙의 **단일 예외**. 미러링 기준가·평가·
        # 주문 검증이 전부 daily_prices를 본다(없으면 첫 코어 매수가 '기준가 없음'으로 막힌다 —
        # 153130 때와 같은 문제). 이 값은 8/3~10/1 41일 전부 정규장 종가와 같았다.
        try:
            core = etf_daily_rows(CORE_TICKER, date, date) if closed else []  # 장중 값을 종가로 쓰지 않는다
            if core:
                db.execute_batch([(DAILY_UPSERT, r) for r in core])
                log.info("코어 ETF %s 일봉 %d행", CORE_TICKER, len(core))
            elif closed:
                log.warning("코어 ETF %s 일봉 없음", CORE_TICKER)
        except Exception as e:
            log.warning("코어 ETF 일봉 실패(%s) — 미러링은 보유 매입가로 폴백한다", str(e)[:60])

        try:
            # 종목별 호출이라 전 종목은 비현실적 — 시총 상위만. 상장목록 폴백 경로에선
            # 시총 순위를 못 매기지만 건너뛸 이유는 없다: 전날까지 받던 종목을 그대로
            # 쓰면 된다(시총 상위는 며칠 새 거의 안 바뀐다). 예전엔 건너뛰어 9/16 수급이 비었다.
            if listing is not None:
                flow_tickers = watchlist(30, listing)
            else:
                flow_tickers = [str(r["ticker"]) for r in db.query("SELECT DISTINCT ticker FROM investor_flows")]
                log.info("상장목록 없음 — 기존 수급 종목 %d개로 계속", len(flow_tickers))
            if flow_tickers:
                upsert_flows(db, load_flows(flow_tickers))
            else:
                log.warning("수급 대상 종목 없음 — 건너뜀 (보조 데이터)")
        except Exception as e:
            log.warning("수급 수집 실패 — 스킵 (보조 데이터): %s", e)

        try:
            upsert_indices(db, date)
        except Exception as e:
            # 벤치마크가 비면 계좌 수익률의 알파를 못 잰다 — 배치 실패로 드러낸다
            log.error("지수 수집 실패: %s", e)
            rc = 1

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

    # 3) 일봉 — 방금 수집한 분봉의 정규장 봉에서 파생. 분봉을 안 받은 실행(스모크·--skip-minute·
    # 제공범위 밖 과거일)과 장중 실행은 일봉을 쓰지 않는다. 과거분 복구는 backfill_daily.py.
    if db is not None:
        if a.tickers or skip_minute or not closed:
            log.info("일봉 파생 생략 (스모크·분봉 생략·장중 실행)")
        else:
            rows = [r for r in rows_from_parquet(date, a.out) if r[0] in valid]
            if rows:
                db.execute_batch([(DAILY_UPSERT, r) for r in rows])
                log.info("daily_prices upsert(분봉 정규장 파생): %d행", len(rows))
            else:
                log.error("거래일인데 daily_prices 0행 — 실패 처리")
                rc = 1

        # 4) 계좌 스냅샷 + AI 판단 수익률 배치 (trading DB)
        tdb = Turso.from_env("TRADING")
        if tdb is None:
            log.warning("TURSO_TRADING_* env 미설정 — 스냅샷·AI 수익률 배치 건너뜀")
        else:
            # 키움 동기화와 스냅샷은 '기준일의 장이 끝난 뒤, 다음 장이 열리기 전'에만 한다.
            # 스냅샷은 지금의 키움 총자산을 date 15:30에 적는다 — 과거 날짜로 돌리면 그날 곡선이
            # 오늘 값으로 덮이고, 장중이면 장중 평가가 종가 평가로 남는다. 동기화도 final이라
            # 장중에 돌면 체결 전인 주문이 평단 추정으로 굳는다. 수집이 50분 넘게 걸리므로
            # 시작 시각이 아니라 지금 시각으로 다시 본다(08시대 시작분이 09시를 넘긴다).
            if date == today and closed and business_date(datetime.now(KST)) == today:
                # ACCOUNT는 웹이 자체 체결하지 않는다 — 키움 미러링(decide 스텝)이 장중에
                # 키움 잔고를 웹에 반영한다. 마감 후 여기서 한 번 더 동기화해 EOD 값이
                # 영웅문 S#와 맞게 한다(키움 조회는 마감 후에도 된다). 그 뒤 스냅샷.
                import os

                acct = int(os.environ.get("AI_ACCOUNT_ID") or 0)
                if acct and os.environ.get("KIWOOM_APP_KEY"):
                    try:
                        import kiwoom_order as ko

                        # final: 장중 동기화가 미체결이라 비워 둔 체결 기록을 여기서 확정한다
                        ko.sync_from_kiwoom(tdb, ko.KiwoomOrderClient(), acct, date, final=True)
                    except Exception as e:
                        log.warning("키움 잔고 동기화 실패 — 스킵: %s", e)
                # 총자산은 키움 추정예탁자산이 기준이고 종가는 그게 없을 때의 폴백일 뿐이라,
                # 일봉이 비어도(분봉 실패일) 스냅샷은 남긴다 — 곡선에 구멍을 내지 않는다.
                snapshot_accounts(tdb, {r[0]: r[5] for r in rows}, date)
            # 달력 종목의 기준일 일봉이 없으면 채점하지 않는다. 그날이 달력에서 빠져 n거래일 뒤가
            # 하루씩 밀리고 그날 판단엔 'holiday'가 붙는다(분봉 수집이 앞쪽에서 끊긴 날).
            if date == today and not db.query(
                    "SELECT 1 FROM daily_prices WHERE ticker = ? AND date = ?", (CALENDAR_TICKER, date)):
                log.warning("%s %s 일봉이 아직 없다 — 채점 건너뜀", date, CALENDAR_TICKER)
            else:
                try:
                    update_ai_returns(tdb, db)
                except Exception as e:
                    log.warning("AI 수익률 배치 실패 — 스킵: %s", e)
    if not a.date and not a.tickers and not closed:
        # 기준일 실행이 장중에 시작됐다(16시간 넘게 밀린 예약 실행 등) — 일봉·스냅샷이 안 쓰였다
        log.error("%s 장 마감 전에 시작한 수집 — 일봉·스냅샷 없이 끝났다, 실패 처리", date)
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
