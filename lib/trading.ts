// 주문·체결·잔고 DB 레이어 — 라이브 계좌(ACCOUNT) 전용. 서버 전용.
//
// 체결은 **키움이 한다**. 웹이 네이버 분봉으로 자체 체결하던 경로(settleOwnerOrders)는
// 제거했다 — 웹이 먼저 FILLED로 확정하면 키움 동기화가 PENDING만 보므로 손대지 못해,
// 실제와 무관한 체결가가 영구히 남았다.
import { tradingDb } from "@/lib/db";
import { getMinuteBars, latestClose, prevDayClose } from "@/lib/minutes";
import { cutBars } from "@/lib/engine/settle";
import { estimateCost } from "@/lib/engine/fill";
import { priceLimits, validateLimitPrice } from "@/lib/engine/rules";
import type { OrderReq, Side } from "@/lib/engine/types";

export type Owner = { type: "ACCOUNT"; id: number };

const nowKst = () =>
  new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 16).replace("T", " ");

async function ownerCash(owner: Owner): Promise<number> {
  const rs = await tradingDb().execute({
    sql: "SELECT cash FROM accounts WHERE id = ?",
    args: [owner.id],
  });
  if (!rs.rows.length) throw new Error("계좌 없음");
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
    // 키움 동기화된 평가손익(수수료·세금 반영). null이면 계산 폴백(미동기화).
    kiwoomPnl: r.pnl == null ? null : Number(r.pnl),
  }));
}

/**
 * 주문 접수. 접수 시점 검증(호가단위·가격제한폭·잔고·현금)에서 걸리면 REJECTED로
 * 기록하고, 통과하면 PENDING 저장. 체결·확정은 키움 미러링(collector/kiwoom_order.py)이 한다.
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

/** 포트폴리오 평가. ACCOUNT는 키움이 기준 — 키움이 동기화한 평가손익·추정예탁자산을
 *  그대로 쓴다(수수료·세금·예상 매도제비용 반영). 없으면(미동기화) 계산 폴백. */
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
  const est = await accountEstAsset(owner.id);
  return { cash, positions: valued, equity: est ?? cash + positionsValue };
}

async function accountEstAsset(id: number): Promise<number | null> {
  const rs = await tradingDb().execute({ sql: "SELECT est_asset FROM accounts WHERE id = ?", args: [id] });
  const v = rs.rows[0]?.est_asset;
  return v == null ? null : Number(v);
}
