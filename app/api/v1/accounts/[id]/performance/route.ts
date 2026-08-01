// 수익률 곡선 + 벤치마크. MDD·샤프 등 지표 계산은 6단계에서 추가.
import { NextResponse } from "next/server";
import { marketDb, tradingDb } from "@/lib/db";

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const snaps = await tradingDb().execute({
    sql: "SELECT ts, equity, cash FROM portfolio_snapshots WHERE owner_type = 'ACCOUNT' AND owner_id = ? ORDER BY ts",
    args: [Number(id)],
  });
  const from = snaps.rows.length ? String(snaps.rows[0].ts).slice(0, 10) : null;
  const indices = from
    ? (
        await marketDb().execute({
          sql: "SELECT code, date, close FROM indices WHERE date >= ? ORDER BY date",
          args: [from],
        })
      ).rows
    : [];
  return NextResponse.json({ snapshots: snaps.rows, indices });
}
