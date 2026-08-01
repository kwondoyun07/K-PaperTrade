// 리플레이 세션 상태 + 잔고·보유 조회
import { NextResponse } from "next/server";
import { tradingDb } from "@/lib/db";
import { getPositions } from "@/lib/trading";
import { jerr } from "@/lib/api";

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const rs = await tradingDb().execute({
    sql: "SELECT id, name, date, tickers, cursor_ts, initial_cash, cash, status, result_json FROM replay_sessions WHERE id = ?",
    args: [Number(id)],
  });
  if (!rs.rows.length) return jerr("세션 없음", 404);
  const s = rs.rows[0];
  const positions = await getPositions({ type: "REPLAY", id: Number(id) });
  return NextResponse.json({
    id: Number(s.id),
    name: s.name,
    date: s.date,
    tickers: JSON.parse(String(s.tickers)),
    cursor: s.cursor_ts,
    initialCash: Number(s.initial_cash),
    cash: Number(s.cash),
    status: s.status,
    result: s.result_json ? JSON.parse(String(s.result_json)) : null,
    positions,
  });
}
