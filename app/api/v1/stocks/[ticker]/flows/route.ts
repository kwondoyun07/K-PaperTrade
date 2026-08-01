import { NextResponse } from "next/server";
import { marketDb } from "@/lib/db";
import { qs } from "@/lib/api";

export async function GET(req: Request, ctx: { params: Promise<{ ticker: string }> }) {
  const { ticker } = await ctx.params;
  const limit = Math.min(Number(qs(req).get("limit") ?? 60), 250);
  const rs = await marketDb().execute({
    sql: "SELECT date, individual, foreigner, institution FROM investor_flows WHERE ticker = ? ORDER BY date DESC LIMIT ?",
    args: [ticker, limit],
  });
  return NextResponse.json({ ticker, flows: [...rs.rows].reverse() });
}
