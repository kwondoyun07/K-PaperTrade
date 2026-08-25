// 수익률 곡선 + 벤치마크 + 지표(MDD·샤프·누적수익률)
import { NextResponse } from "next/server";
import { marketDb, tradingDb } from "@/lib/db";
import { dailyReturns, maxDrawdownPct, sharpeRatio } from "@/lib/metrics";
import { caller, guardOwner } from "@/lib/owner";

export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const denied = await guardOwner(await caller(req), "accounts", Number(id));
  if (denied) return denied;
  const snaps = await tradingDb().execute({
    sql: "SELECT ts, equity, cash FROM portfolio_snapshots WHERE owner_type = 'ACCOUNT' AND owner_id = ? ORDER BY ts",
    args: [Number(id)],
  });
  // 누적수익률의 기준은 시드다. 첫 스냅샷을 기준으로 쓰면 그 한 점이 틀렸을 때
  // 곡선 전체가 통째로 어긋난다 — 실제로 8/5 스냅샷이 매수대금을 차감하지 않아
  // -13.97%로 표시되고 있었다(실제 +1.6%).
  const seed = await tradingDb().execute({
    sql: "SELECT initial_cash FROM accounts WHERE id = ?",
    args: [Number(id)],
  });
  const base = Number(seed.rows[0]?.initial_cash ?? 0);
  const from = snaps.rows.length ? String(snaps.rows[0].ts).slice(0, 10) : null;
  const indices = from
    ? (
        await marketDb().execute({
          sql: "SELECT code, date, close FROM indices WHERE date >= ? ORDER BY date",
          args: [from],
        })
      ).rows
    : [];

  const equity = snaps.rows.map((r) => Number(r.equity));
  const metrics =
    equity.length >= 2
      ? {
          returnPct: base > 0 ? (equity[equity.length - 1] / base - 1) * 100 : 0,
          mddPct: maxDrawdownPct(equity),
          sharpe: sharpeRatio(dailyReturns(equity)),
        }
      : null;

  return NextResponse.json({ snapshots: snaps.rows, indices, metrics });
}
