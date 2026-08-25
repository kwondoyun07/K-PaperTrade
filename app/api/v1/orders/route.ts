import { NextResponse } from "next/server";
import { z } from "zod";
import { tradingDb } from "@/lib/db";
import { placeOrder } from "@/lib/trading";
import { jerr, nowKst, qs } from "@/lib/api";
import { caller, guardOwner } from "@/lib/owner";

const CreateOrder = z.object({
  accountId: z.number().int().positive(),
  ticker: z.string().regex(/^\d{6}$/),
  side: z.enum(["BUY", "SELL"]),
  type: z.enum(["MARKET", "LIMIT"]),
  qty: z.number().int().positive(),
  limitPrice: z.number().int().positive().optional(),
});

export async function POST(req: Request) {
  const body = CreateOrder.safeParse(await req.json().catch(() => null));
  if (!body.success) return jerr(body.error.issues[0].message);
  const { accountId, ticker, ...rest } = body.data;
  const denied = await guardOwner(await caller(req), "accounts", accountId);
  if (denied) return denied;
  try {
    const order = await placeOrder({ type: "ACCOUNT", id: accountId }, ticker, rest, nowKst());
    return NextResponse.json(order, { status: 201 });
  } catch (e) {
    return jerr(String(e), 400);
  }
}

export async function GET(req: Request) {
  const accountId = Number(qs(req).get("account_id"));
  if (!accountId) return jerr("account_id 파라미터 필요");
  const denied = await guardOwner(await caller(req), "accounts", accountId);
  if (denied) return denied;
  const rs = await tradingDb().execute({
    sql:
      "SELECT o.id, o.ticker, o.side, o.order_type, o.qty, o.limit_price, o.status, o.reject_reason, o.ordered_at, " +
      "e.price AS exec_price, e.qty AS exec_qty, e.commission, e.tax, e.executed_at, " +
      // 주문을 낸 AI 판단의 근거. orders에 판단 id를 안 들고 있어 (종목·구분·같은 날·
      // 주문 직전) 으로 되짚는다. 하루 사이클이 3회라 같은 종목·같은 구분이 두 번
      // 나올 수 있어 가장 최근 것을 쓴다 — 실주문 11건 전부 정확히 맞았다.
      "(SELECT a.reason_summary FROM ai_decisions a " +
      " WHERE a.ticker = o.ticker AND a.action = o.side " +
      "   AND substr(a.ts, 1, 10) = substr(o.ordered_at, 1, 10) " +
      "   AND substr(a.ts, 1, 16) <= o.ordered_at " +
      " ORDER BY a.ts DESC LIMIT 1) AS reason " +
      "FROM orders o LEFT JOIN executions e ON e.order_id = o.id " +
      "WHERE o.owner_type = 'ACCOUNT' AND o.owner_id = ? ORDER BY o.id DESC LIMIT 100",
    args: [accountId],
  });
  // 매도 실현손익 = (체결가 - 평균매입원가) × 수량 - 매도제비용.
  // 취득원가에 매수 수수료를 넣는다(모의계좌는 0.35%라 무시하면 손익이 부풀려진다).
  // 이동평균법 — 키움 pur_pric과 같은 방식. LIMIT 100에 걸리면 평균이 어긋나므로
  // 손익만은 전체 이력으로 따로 계산한다.
  const hist = await tradingDb().execute({
    sql:
      "SELECT o.id, o.ticker, o.side, e.price, e.qty, e.commission, e.tax " +
      "FROM orders o JOIN executions e ON e.order_id = o.id " +
      "WHERE o.owner_type = 'ACCOUNT' AND o.owner_id = ? ORDER BY o.id",
    args: [accountId],
  });
  const book = new Map<string, { qty: number; cost: number }>();
  const realized = new Map<number, number>();
  for (const r of hist.rows) {
    const t = String(r.ticker);
    const qty = Number(r.qty);
    const price = Number(r.price);
    const b = book.get(t) ?? { qty: 0, cost: 0 };
    if (String(r.side) === "BUY") {
      b.qty += qty;
      b.cost += price * qty + Number(r.commission ?? 0);
    } else {
      // 보유가 없는데 매도가 잡히면(웹에 없는 키움 거래) 원가를 알 수 없다 — 체결가를
      // 원가로 봐 손익 0으로 두고, 없는 이익을 지어내지 않는다.
      const unit = b.qty > 0 ? b.cost / b.qty : price;
      realized.set(
        Number(r.id),
        Math.round((price - unit) * qty - Number(r.commission ?? 0) - Number(r.tax ?? 0)),
      );
      b.cost = Math.max(b.cost - unit * qty, 0);
      b.qty = Math.max(b.qty - qty, 0);
    }
    book.set(t, b);
  }

  const orders = rs.rows.map((r) => ({ ...r, realized: realized.get(Number(r.id)) ?? null }));
  return NextResponse.json({ orders });
}
