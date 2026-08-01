import { NextResponse } from "next/server";
import { marketDb } from "@/lib/db";
import { qs } from "@/lib/api";

export async function GET(req: Request, ctx: { params: Promise<{ ticker: string }> }) {
  const { ticker } = await ctx.params;
  const p = qs(req);
  const from = p.get("from");
  const to = p.get("to");
  const rs = from
    ? await marketDb().execute({
        sql: "SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker = ? AND date >= ? AND date <= ? ORDER BY date",
        args: [ticker, from, to ?? "9999-12-31"],
      })
    : await marketDb().execute({
        sql: "SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker = ? ORDER BY date DESC LIMIT 120",
        args: [ticker],
      });
  const rows = from ? rs.rows : [...rs.rows].reverse();
  return NextResponse.json({ ticker, bars: rows });
}
