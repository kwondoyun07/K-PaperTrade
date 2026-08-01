import { NextResponse } from "next/server";
import { z } from "zod";
import { tradingDb } from "@/lib/db";
import { placeOrder } from "@/lib/trading";
import { jerr, nowKst, qs } from "@/lib/api";

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
  const rs = await tradingDb().execute({
    sql:
      "SELECT o.id, o.ticker, o.side, o.order_type, o.qty, o.limit_price, o.status, o.reject_reason, o.ordered_at, " +
      "e.price AS exec_price, e.qty AS exec_qty, e.commission, e.tax, e.executed_at " +
      "FROM orders o LEFT JOIN executions e ON e.order_id = o.id " +
      "WHERE o.owner_type = 'ACCOUNT' AND o.owner_id = ? ORDER BY o.id DESC LIMIT 100",
    args: [accountId],
  });
  return NextResponse.json({ orders: rs.rows });
}
