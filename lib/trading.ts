// 주문·체결·잔고 DB 레이어 — 라이브 계좌(ACCOUNT) 기준. Owner 유니언에 REPLAY가
// 남은 건 제거된 리플레이 기능의 잔재다. 머니 경로를 건드리는 리팩터링이라 그대로 뒀다.
// owner_type/owner_id로 동일 테이블·동일 체결 엔진을 공유한다. 서버 전용.
import { tradingDb } from "@/lib/db";
import { getMinuteBars, latestClose, prevDayClose } from "@/lib/minutes";
import { cutBars, settlePending } from "@/lib/engine/settle";
import { estimateCost } from "@/lib/engine/fill";
import { priceLimits, validateLimitPrice } from "@/lib/engine/rules";
import type { OrderReq, Side } from "@/lib/engine/types";

export type Owner = { type: "ACCOUNT" | "REPLAY"; id: number };

const nowKst = () =>
  new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 16).replace("T", " ");

async function ownerCash(owner: Owner): Promise<number> {
  const table = owner.type === "ACCOUNT" ? "accounts" : "replay_sessions";
  const rs = await tradingDb().execute({
    sql: `SELECT cash FROM ${table} WHERE id = ?`,
    args: [owner.id],
  });
  if (!rs.rows.length) throw new Error("계좌/세션 없음");
  return Number(rs.rows[0].cash);
}

export async function getPositions(owner: Owner) {
  const rs = await tradingDb().execute({
    sql: "SELECT ticker, qty, avg_price, pnl FROM positions WHERE owner_type = ? AND owner_id = ? AND qty > 0",
    args: [owner.type, owner.id],
  });
  return rs.rows.map((r) => ({
    ticker: String(r.ticker),
    qty: Number(r.qty),
    avgPrice: Number(r.avg_price),
    // 키움 동기화된 평가손익(수수료·세금 반영). null이면 계산 폴백(REPLAY·미동기화).
    kiwoomPnl: r.pnl == null ? null : Number(r.pnl),
  }));
}

/**
 * 주문 접수. 접수 시점 검증(호가단위·가격제한폭·잔고·현금)에서 걸리면 REJECTED로
 * 기록하고, 통과하면 PENDING 저장. 체결은 settleOwnerOrders()가 다음 분봉에서 처리.
 */
export async function placeOrder(
  owner: Owner,
  ticker: string,
  req: OrderReq,
  orderedAt: string,
): Promise<{ id: number; status: string; rejectReason?: string }> {
  const date = orderedAt.slice(0, 10);
  let reject: string | null = null;

  if (req.type === "LIMIT") {
    const err = req.limitPrice == null ? "지정가없음" : validateLimitPrice(req.limitPrice);
    if (err) reject = err.includes("호가단위") ? "호가단위" : err;
    else {
      const pdc = await prevDayClose(ticker, date);
      if (pdc != null) {
        const { up, down } = priceLimits(pdc);
        if (req.limitPrice! > up || req.limitPrice! < down) reject = "가격제한폭";
      }
    }
  }
  if (!reject && req.side === "SELL") {
    const pos = (await getPositions(owner)).find((p) => p.ticker === ticker);
    if (!pos || pos.qty < req.qty) reject = "잔고부족";
  }
  if (!reject && req.side === "BUY") {
    // 접수 시점 대략 검증(지정가 또는 접수 시각 기준 최근가). 최종 검증은 체결 시점.
    const ref = req.limitPrice ?? (await refPrice(ticker, orderedAt));
    if (ref != null) {
      const { total } = estimateCost("BUY", ref, req.qty);
      if (total > (await ownerCash(owner))) reject = "현금부족";
    }
  }

  const rs = await tradingDb().execute({
    sql:
      "INSERT INTO orders (owner_type, owner_id, ticker, side, order_type, qty, limit_price, status, reject_reason, ordered_at, created_at) " +
      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
    args: [
      owner.type, owner.id, ticker, req.side, req.type, req.qty,
      req.limitPrice ?? null, reject ? "REJECTED" : "PENDING", reject, orderedAt, nowKst(),
    ],
  });
  return {
    id: Number(rs.rows[0].id),
    status: reject ? "REJECTED" : "PENDING",
    rejectReason: reject ?? undefined,
  };
}

async function refPrice(ticker: string, orderedAt: string): Promise<number | null> {
  const bars = cutBars(await getMinuteBars(ticker, orderedAt.slice(0, 10)), orderedAt);
  if (bars.length) return bars[bars.length - 1].close;
  return latestClose(ticker);
}

export type SettleResult = {
  orderId: number;
  ticker: string;
  side: Side;
  status: "FILLED" | "REJECTED";
  reason?: string;
  price?: number;
  qty?: number;
  ts?: string; // 체결 분봉 시각
};

/**
 * PENDING 주문 정산. cursor를 주면 그 이전 분봉만 사용한다.
 * 라이브는 cursor 없이 현재까지 쌓인 분봉으로 정산한다.
 */
export async function settleOwnerOrders(owner: Owner, cursor?: string): Promise<SettleResult[]> {
  const db = tradingDb();
  const pending = await db.execute({
    sql: "SELECT id, ticker, side, order_type, qty, limit_price, ordered_at FROM orders WHERE owner_type = ? AND owner_id = ? AND status = 'PENDING' ORDER BY id",
    args: [owner.type, owner.id],
  });
  const results: SettleResult[] = [];
  const cashTable = owner.type === "ACCOUNT" ? "accounts" : "replay_sessions";

  for (const row of pending.rows) {
    const ticker = String(row.ticker);
    const orderedAt = String(row.ordered_at);
    const date = orderedAt.slice(0, 10);
    const order: OrderReq = {
      side: String(row.side) as Side,
      type: String(row.order_type) as OrderReq["type"],
      qty: Number(row.qty),
      limitPrice: row.limit_price == null ? undefined : Number(row.limit_price),
    };
    let bars = await getMinuteBars(ticker, date);
    if (cursor) bars = cutBars(bars, cursor);
    const pdc = (await prevDayClose(ticker, date)) ?? bars[0]?.open;
    if (!bars.length || pdc == null) continue;

    const r = settlePending(order, orderedAt, bars, pdc);
    if (r.status === "PENDING") continue;

    // 상태 가드가 핵심이다. 장중 폴링(/quotes)과 배치 정산(/cron/settle)이 같은
    // PENDING 주문을 동시에 집을 수 있는데, 가드가 없으면 둘 다 체결시켜
    // executions가 두 번 쌓이고 현금이 두 번 빠진다. rowsAffected로 선점을 확인한다.
    if (r.status === "REJECTED") {
      const upd = await db.execute({
        sql: "UPDATE orders SET status = 'REJECTED', reject_reason = ? WHERE id = ? AND status = 'PENDING'",
        args: [r.reason, Number(row.id)],
      });
      if (upd.rowsAffected === 0) continue; // 다른 경로가 이미 확정했다
      results.push({ orderId: Number(row.id), ticker, side: order.side, status: "REJECTED", reason: r.reason });
      continue;
    }

    const { price, qty, commission, tax, ts } = r.fill;
    const amount = price * qty;
    const cash = await ownerCash(owner);
    if (order.side === "BUY" && amount + commission > cash) {
      const upd = await db.execute({
        sql: "UPDATE orders SET status = 'REJECTED', reject_reason = '현금부족' WHERE id = ? AND status = 'PENDING'",
        args: [Number(row.id)],
      });
      if (upd.rowsAffected === 0) continue;
      results.push({ orderId: Number(row.id), ticker, side: order.side, status: "REJECTED", reason: "현금부족" });
      continue;
    }

    const stmts = [
      {
        sql: "INSERT INTO executions (order_id, price, qty, commission, tax, executed_at) VALUES (?, ?, ?, ?, ?, ?)",
        args: [Number(row.id), price, qty, commission, tax, ts],
      },
    ];
    if (order.side === "BUY") {
      stmts.push(
        {
          sql:
            "INSERT INTO positions (owner_type, owner_id, ticker, qty, avg_price) VALUES (?, ?, ?, ?, ?) " +
            "ON CONFLICT(owner_type, owner_id, ticker) DO UPDATE SET " +
            "avg_price = CAST(ROUND((positions.avg_price * positions.qty + excluded.avg_price * excluded.qty) * 1.0 / (positions.qty + excluded.qty)) AS INTEGER), " +
            "qty = positions.qty + excluded.qty",
          args: [owner.type, owner.id, ticker, qty, price],
        },
        {
          sql: `UPDATE ${cashTable} SET cash = cash - ? WHERE id = ?`,
          args: [amount + commission, owner.id],
        },
      );
    } else {
      stmts.push(
        {
          sql: "UPDATE positions SET qty = qty - ? WHERE owner_type = ? AND owner_id = ? AND ticker = ?",
          args: [qty, owner.type, owner.id, ticker],
        },
        {
          sql: `UPDATE ${cashTable} SET cash = cash + ? WHERE id = ?`,
          args: [amount - commission - tax, owner.id],
        },
      );
    }
    // 선점(PENDING→FILLED)과 부수효과를 한 트랜잭션에 묶는다. 선점에 실패하면
    // 다른 경로가 이미 처리한 주문이므로 아무것도 반영하지 않고 롤백한다.
    const tx = await db.transaction("write");
    try {
      const claim = await tx.execute({
        sql: "UPDATE orders SET status = 'FILLED' WHERE id = ? AND status = 'PENDING'",
        args: [Number(row.id)],
      });
      if (claim.rowsAffected === 0) {
        await tx.rollback();
        continue;
      }
      for (const s of stmts) await tx.execute(s);
      await tx.commit();
    } catch (e) {
      await tx.rollback().catch(() => {});
      throw e;
    }
    results.push({ orderId: Number(row.id), ticker, side: order.side, status: "FILLED", price, qty, ts });
  }
  return results;
}

/** 포트폴리오 평가. ACCOUNT는 키움이 기준 — 키움이 동기화한 평가손익·추정예탁자산을
 *  그대로 쓴다(수수료·세금·예상 매도제비용 반영). 없으면(REPLAY·미동기화) 계산 폴백. */
export async function getPortfolio(owner: Owner) {
  const cash = await ownerCash(owner);
  const positions = await getPositions(owner);
  const valued = await Promise.all(
    positions.map(async (p) => {
      const cur = (await latestClose(p.ticker)) ?? p.avgPrice;
      const cost = p.avgPrice * p.qty;
      const pnl = p.kiwoomPnl ?? (cur - p.avgPrice) * p.qty; // 키움 실손익 우선
      return {
        ticker: p.ticker,
        qty: p.qty,
        avgPrice: p.avgPrice,
        currentPrice: cur,
        value: cur * p.qty,
        pnl,
        returnPct: cost > 0 ? (pnl / cost) * 100 : 0,
      };
    }),
  );
  const positionsValue = valued.reduce((s, p) => s + p.value, 0);
  // 키움 추정예탁자산이 있으면 총자산으로 쓴다(예상 매도제비용까지 반영해 S#와 일치).
  const est = owner.type === "ACCOUNT" ? await accountEstAsset(owner.id) : null;
  return { cash, positions: valued, equity: est ?? cash + positionsValue };
}

async function accountEstAsset(id: number): Promise<number | null> {
  const rs = await tradingDb().execute({ sql: "SELECT est_asset FROM accounts WHERE id = ?", args: [id] });
  const v = rs.rows[0]?.est_asset;
  return v == null ? null : Number(v);
}
