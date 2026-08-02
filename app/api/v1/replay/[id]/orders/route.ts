// 리플레이 주문 — ordered_at은 클라이언트가 아니라 서버 DB의 세션 커서(가상 시각).
// 체결은 다음 tick에서 커서 이전 분봉으로만 정산된다.
import { NextResponse } from "next/server";
import { z } from "zod";
import { tradingDb } from "@/lib/db";
import { placeOrder } from "@/lib/trading";
import { jerr } from "@/lib/api";
import { caller, guardOwner } from "@/lib/owner";

const ReplayOrder = z.object({
  ticker: z.string().regex(/^\d{6}$/),
  side: z.enum(["BUY", "SELL"]),
  type: z.enum(["MARKET", "LIMIT"]),
  qty: z.number().int().positive(),
  limitPrice: z.number().int().positive().optional(),
});

export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const denied = await guardOwner(await caller(req), "replay_sessions", Number(id));
  if (denied) return denied;
  const body = ReplayOrder.safeParse(await req.json().catch(() => null));
  if (!body.success) return jerr(body.error.issues[0].message);

  const rs = await tradingDb().execute({
    sql: "SELECT id, tickers, cursor_ts, status FROM replay_sessions WHERE id = ?",
    args: [Number(id)],
  });
  if (!rs.rows.length) return jerr("세션 없음", 404);
  const s = rs.rows[0];
  if (String(s.status) !== "ACTIVE") return jerr("종료된 세션", 409);
  const tickers: string[] = JSON.parse(String(s.tickers));
  if (!tickers.includes(body.data.ticker)) return jerr("세션에 없는 종목");

  const { ticker, ...req_ } = body.data;
  const order = await placeOrder(
    { type: "REPLAY", id: Number(s.id) },
    ticker,
    req_,
    String(s.cursor_ts),
  );
  return NextResponse.json(order, { status: 201 });
}
