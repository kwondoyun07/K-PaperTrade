"""키움 모의계좌 주문 미러링 (v1.5).

자체 체결 엔진에서 FILLED된 라이브 계좌 주문을 키움 **모의투자** 계좌에도 내보내고,
응답 주문번호를 orders.broker_order_id에 기록해 대사할 수 있게 한다.

Actions 배치에서만 돌린다. 키움 토큰은 IP 화이트리스트에 묶여 있어
토큰 발급→주문을 반드시 같은 런 안에서 끝내야 한다(웹 서버로 토큰을 넘기지 않는다).

실행:
    uv run python kiwoom_order.py --account-id 1              # 드라이런(기본)
    uv run python kiwoom_order.py --accounts                  # 계좌번호 조회(ka00001)
    uv run python kiwoom_order.py --account-id 1 --send       # 실제 전송

--- 키움 문서 확인 결과 (openapi.kiwoom.com API 가이드, 2026-08-02) ---
주문:   POST /api/dostk/ordr
        api-id  kt10000 매수 / kt10001 매도 / kt10002 정정 / kt10003 취소
        body    dmst_stex_tp(KRX|NXT|SOR), stk_cd, ord_qty, ord_uv, trde_tp
        trde_tp 0:보통(지정가) 3:시장가 5:조건부지정가 6:최유리 7:최우선
                10:보통(IOC) 13:시장가(IOC) 61:장시작전시간외 62:시간외단일가 81:장마감후시간외
        응답    ord_no(주문번호), dmst_stex_tp, return_code, return_msg
계좌:   POST /api/dostk/acnt
        api-id  ka00001 계좌번호조회 / kt00001 예수금상세현황 / kt00018 계좌평가잔고내역
        → 주문 body에 계좌번호 필드가 없다. 앱키가 계좌에 묶여 있고,
          계좌번호는 ka00001로 조회한다.
모의투자는 대체거래소(NXT) 매매·계좌조회 미지원 → dmst_stex_tp는 KRX 고정.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

from turso import Turso

log = logging.getLogger("mirror")

# 모의투자 전용. 실전 호스트 문자열은 이 파일에 존재해서는 안 된다.
MOCK_HOST = "https://mockapi.kiwoom.com"
ORDER_PATH = "/api/dostk/ordr"
ACNT_PATH = "/api/dostk/acnt"
TR_BUY = "kt10000"
TR_SELL = "kt10001"
TR_ACCOUNTS = "ka00001"
EXCHANGE = "KRX"  # 모의투자는 NXT 미지원

# 미러링 상한 — 버그가 나도 손실 규모가 유한하도록 강제한다.
MAX_QTY = 1_000
MAX_NOTIONAL = 10_000_000  # 주문 1건 추정 금액(원)
MAX_ORDERS_PER_RUN = 20
MAX_SINCE_DAYS = 7  # --since를 과거로 열어주면 히스토리 전체가 한 번에 나갈 수 있다

REQ_INTERVAL = 1.1  # 키움 유량 제한: API ID당 초당 1회

KST = timezone(timedelta(hours=9))


class LimitError(ValueError):
    """상한·형식 위반. 주문을 만들지 않고 즉시 중단시킨다."""


def order_payload(
    side: str,
    ticker: str,
    qty: int,
    order_type: str,
    limit_price: int | None,
    ref_price: int,
) -> dict:
    """kt10000/kt10001 요청 body. ref_price는 금액 상한 검증용(체결가)."""
    if side not in ("BUY", "SELL"):
        raise LimitError(f"매매구분 오류: {side}")
    if order_type not in ("MARKET", "LIMIT"):
        raise LimitError(f"주문유형 오류: {order_type}")
    if not (len(ticker) == 6 and ticker.isdigit()):
        raise LimitError(f"종목코드 오류: {ticker}")
    if not 0 < qty <= MAX_QTY:
        raise LimitError(f"수량 상한 위반: {qty} (최대 {MAX_QTY})")
    if order_type == "LIMIT" and not limit_price:
        raise LimitError("지정가 주문에 limit_price 없음")
    price = limit_price if order_type == "LIMIT" else ref_price
    if price <= 0:
        raise LimitError("기준가 없음 — 금액 상한을 검증할 수 없다")
    if price * qty > MAX_NOTIONAL:
        raise LimitError(f"금액 상한 위반: {price * qty:,}원 (최대 {MAX_NOTIONAL:,})")

    return {
        "dmst_stex_tp": EXCHANGE,
        "stk_cd": ticker,
        "ord_qty": str(qty),
        "ord_uv": "" if order_type == "MARKET" else str(limit_price),
        "trde_tp": "3" if order_type == "MARKET" else "0",
    }


def tr_for(side: str) -> str:
    return TR_BUY if side == "BUY" else TR_SELL


class KiwoomOrderClient:
    """모의투자 주문 클라이언트. 호스트는 상수 고정이라 실전으로 돌릴 수 없다."""

    def __init__(self, app_key: str | None = None, app_secret: str | None = None):
        self.app_key = app_key or os.environ.get("KIWOOM_APP_KEY", "")
        self.app_secret = app_secret or os.environ.get("KIWOOM_APP_SECRET", "")
        if not self.app_key or not self.app_secret:
            raise RuntimeError("KIWOOM_APP_KEY / KIWOOM_APP_SECRET 미설정")
        self._client = httpx.Client(timeout=20.0)
        self._token = ""
        self._last_req = 0.0

    def token(self) -> str:
        if self._token:
            return self._token
        r = self._client.post(
            f"{MOCK_HOST}/oauth2/token",
            headers={"Content-Type": "application/json;charset=UTF-8"},
            json={
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "secretkey": self.app_secret,
            },
        )
        r.raise_for_status()
        j = r.json()
        if not j.get("token"):
            raise RuntimeError(f"키움 토큰 발급 실패: {j.get('return_msg') or j}")
        self._token = j["token"]
        return self._token

    def _post(self, path: str, api_id: str, body: dict) -> dict:
        wait = REQ_INTERVAL - (time.monotonic() - self._last_req)
        if wait > 0:
            time.sleep(wait)
        self._last_req = time.monotonic()
        r = self._client.post(
            f"{MOCK_HOST}{path}",
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "authorization": f"Bearer {self.token()}",
                "api-id": api_id,
            },
            json=body,
        )
        r.raise_for_status()
        j = r.json()
        if str(j.get("return_code", "0")) not in ("0", "None"):
            raise RuntimeError(f"{api_id}: {j.get('return_msg')} (code={j.get('return_code')})")
        return j

    def accounts(self) -> dict:
        """ka00001 계좌번호조회 — 앱키에 묶인 계좌 목록."""
        return self._post(ACNT_PATH, TR_ACCOUNTS, {})

    def place(self, side: str, payload: dict) -> str:
        j = self._post(ORDER_PATH, tr_for(side), payload)
        ord_no = str(j.get("ord_no") or "").strip()
        if not ord_no:
            raise RuntimeError(f"주문번호 없음: {j}")
        return ord_no


# --- 미러링 대상 조회 ------------------------------------------------------

PENDING_SQL = """
SELECT o.id, o.ticker, o.side, o.order_type, o.qty, o.limit_price, o.ordered_at,
       (SELECT price FROM executions e WHERE e.order_id = o.id ORDER BY e.id DESC LIMIT 1) AS fill_price
FROM orders o
WHERE o.owner_type = 'ACCOUNT'
  AND o.owner_id = ?
  AND o.status = 'FILLED'
  AND COALESCE(o.broker_order_id, '') = ''
  AND o.ordered_at >= ?
ORDER BY o.id
LIMIT ?
"""

# 전송 **전** 선점. Turso.execute는 rowsAffected를 주지 않으므로 RETURNING으로 확인한다.
CLAIM_SQL = (
    "UPDATE orders SET broker_order_id = 'SENDING:'||? "
    "WHERE id = ? AND COALESCE(broker_order_id,'') = '' RETURNING id"
)
# 선점 표식을 쥔 행만 덮어쓴다 — 다른 런이 이미 결론 낸 행을 건드리지 않는다.
RESOLVE_SQL = "UPDATE orders SET broker_order_id = ? WHERE id = ? AND broker_order_id = ?"
# 전송 전에 걸러진 행(형식·상한 위반)은 선점 없이 바로 마킹해 다음 런에서 빠진다.
MARK_SQL = "UPDATE orders SET broker_order_id = ? WHERE id = ? AND COALESCE(broker_order_id,'') = ''"


def ensure_broker_column(db: Turso) -> None:
    """orders.broker_order_id 보장.

    db/migrations는 migrate.mjs가 매번 전부 재실행하므로 비멱등한 ALTER를
    거기 둘 수 없다. 중복 컬럼 오류만 삼키고 넘어간다.
    """
    try:
        db.execute("ALTER TABLE orders ADD COLUMN broker_order_id TEXT")
        log.info("orders.broker_order_id 컬럼 추가")
    except RuntimeError as e:
        if "duplicate column" not in str(e).lower():
            raise


def run_tag() -> str:
    """선점 표식에 붙일 런 식별자 — 어느 런이 쥐고 죽었는지 사람이 추적할 수 있게."""
    return os.environ.get("GITHUB_RUN_ID") or datetime.now(KST).strftime("%Y%m%d%H%M%S")


def valid_since(s: str, today: datetime | None = None) -> str:
    """--since 검증. 형식 오류·미래·너무 과거를 막는다(과거를 열면 히스토리가 통째로 나간다)."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise LimitError(f"--since 형식 오류: {s} (YYYY-MM-DD)")
    d = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=KST)
    now = today or datetime.now(KST)
    days = (now.replace(hour=0, minute=0, second=0, microsecond=0) - d).days
    if days < 0:
        raise LimitError(f"--since 미래 날짜: {s}")
    if days > MAX_SINCE_DAYS:
        raise LimitError(f"--since 과거 {days}일 — 최대 {MAX_SINCE_DAYS}일")
    return s


def mirror(
    db: Turso,
    client: KiwoomOrderClient | None,
    since: str,
    limit: int,
    account_id: int,
) -> int:
    rows = db.query(PENDING_SQL, (account_id, since, limit))
    if not rows:
        log.info("미러링 대상 없음 (account=%s, ordered_at >= %s)", account_id, since)
        return 0

    # 토큰을 루프 전에 미리 받는다. 지연 발급이면 인증·연결 장애가 건별 예외로 잡혀
    # 대상 행이 전부 'FAILED'로 마킹되고, 그 행들은 다시는 조회되지 않는다.
    # 여기서 죽으면 아무것도 마킹되지 않아 다음 런이 그대로 재시도한다.
    if client is not None:
        client.token()

    tag, sent = run_tag(), 0
    for r in rows:
        oid = int(r["id"])
        head = f"order#{oid} {r['ordered_at']} {r['side']} {r['ticker']} x{r['qty']}"
        try:
            payload = order_payload(
                side=str(r["side"]),
                ticker=str(r["ticker"]),
                qty=int(r["qty"]),
                order_type=str(r["order_type"]),
                limit_price=r["limit_price"],
                ref_price=int(r["fill_price"] or 0),
            )
        except LimitError as e:
            # 한 건의 상한 위반이 뒤 주문을 전부 막으면 안 된다. 마킹하고 넘어간다.
            log.warning("%s SKIP: %s", head, e)
            if client is not None:
                db.execute(MARK_SQL, (f"SKIP:{str(e)[:80]}", oid))
            continue

        if client is None:
            print(f"[DRY-RUN] {head}\n          api-id={tr_for(str(r['side']))} "
                  f"POST {MOCK_HOST}{ORDER_PATH}\n          {json.dumps(payload, ensure_ascii=False)}")
            continue

        # 전송 전에 선점한다. 전송 후 기록이면 타임아웃·5xx로 응답만 유실됐을 때
        # 키움엔 주문이 들어갔는데 기록이 없어 다음 런이 같은 주문을 또 낸다.
        claim = f"SENDING:{tag}"
        if not db.query(CLAIM_SQL, (tag, oid)):
            log.warning("%s 선점 실패 — 다른 런이 처리 중", head)
            continue

        try:
            ord_no = client.place(str(r["side"]), payload)
        except Exception as e:  # noqa: BLE001 - 사유를 남기고 다음 행으로
            # 자동 재전송 금지. 중복 주문이 미전송보다 위험하다 — 사람이 확인한다.
            db.execute(RESOLVE_SQL, (f"FAILED:{str(e)[:80]}", oid, claim))
            log.error("%s 전송 실패(사람 확인 필요): %s", head, e)
            continue

        db.execute(RESOLVE_SQL, (ord_no, oid, claim))
        log.info("%s → 키움 주문번호 %s", head, ord_no)
        sent += 1
    return sent


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="키움 모의계좌 주문 미러링")
    p.add_argument("--dry-run", action="store_true", default=True, help="전송 없이 페이로드만 출력(기본)")
    p.add_argument("--send", dest="dry_run", action="store_false", help="실제 전송")
    p.add_argument("--since", help="이 날짜 이후 주문만 YYYY-MM-DD (기본: 오늘 KST)")
    p.add_argument("--limit", type=int, default=MAX_ORDERS_PER_RUN)
    p.add_argument("--account-id", type=int, help="미러링할 계좌 owner_id (필수)")
    p.add_argument("--accounts", action="store_true", help="ka00001 계좌번호조회만 수행")
    a = p.parse_args()

    if a.accounts:
        print(json.dumps(KiwoomOrderClient().accounts(), ensure_ascii=False, indent=2))
        return 0

    # 계좌를 지정하지 않으면 모든 계좌의 체결이 한 키움 계좌로 합쳐 나간다.
    if a.account_id is None or a.account_id <= 0:
        log.error("--account-id 필수 (미러링할 계좌 owner_id)")
        return 2

    try:
        since = valid_since(a.since) if a.since else datetime.now(KST).strftime("%Y-%m-%d")
    except LimitError as e:
        log.error("%s", e)
        return 2
    # 하한이 없으면 --limit -1이 SQLite에서 "무제한"이 된다.
    limit = max(1, min(a.limit, MAX_ORDERS_PER_RUN))

    db = Turso.from_env("TRADING")
    if db is None:
        log.error("TURSO_TRADING_* env 미설정")
        return 1
    ensure_broker_column(db)

    client = None if a.dry_run else KiwoomOrderClient()
    if client is None:
        log.info("드라이런 — 실제 전송 없음")
    sent = mirror(db, client, since, limit, a.account_id)
    log.info("미러링 완료: %d건 전송", sent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
