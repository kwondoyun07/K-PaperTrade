// 리플레이 커서 전진. 커서(가상 시각)는 서버(DB)에만 존재하며, 분봉 조회와
// 주문 정산 모두 이 커서 이전 데이터만 사용한다 — 룩어헤드 서버 강제.
import { NextResponse } from "next/server";
import { z } from "zod";
import { tradingDb } from "@/lib/db";
import { getMinuteBars } from "@/lib/minutes";
import { addMinutes, cutBars } from "@/lib/engine/settle";
import { getPositions, settleOwnerOrders } from "@/lib/trading";
import { jerr } from "@/lib/api";
import { caller, guardOwner } from "@/lib/owner";

const Tick = z.object({
  minutes: z.number().int().min(1).max(390).default(1),
  finish: z.boolean().default(false),
});

export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const denied = await guardOwner(await caller(req), "replay_sessions", Number(id));
  if (denied) return denied;
  const body = Tick.safeParse(await req.json().catch(() => ({})));
  if (!body.success) return jerr(body.error.issues[0].message);

  const db = tradingDb();
  const rs = await db.execute({
    sql: "SELECT id, date, tickers, cursor_ts, initial_cash, cash, status FROM replay_sessions WHERE id = ?",
    args: [Number(id)],
  });
  if (!rs.rows.length) return jerr("세션 없음", 404);
  const s = rs.rows[0];
  if (String(s.status) !== "ACTIVE") return jerr("종료된 세션", 409);

  const date = String(s.date);
  const end = `${date} 15:30`;
  const cur = String(s.cursor_ts ?? `${date} 09:00`);
  const next = addMinutes(cur, body.data.minutes);
  const cursor = next > end ? end : next;

  const owner = { type: "REPLAY", id: Number(s.id) } as const;
  const fills = await settleOwnerOrders(owner, cursor);
  await db.execute({
    sql: "UPDATE replay_sessions SET cursor_ts = ? WHERE id = ?",
    args: [cursor, Number(s.id)],
  });

  let result: Record<string, unknown> | null = null;
  if (body.data.finish || cursor >= end) {
    // 세션 결과: 커서 시점 보유분 평가 + 현금 → 수익률. 세션 간 비교용으로 저장.
    const cashRow = await db.execute({
      sql: "SELECT cash FROM replay_sessions WHERE id = ?",
      args: [Number(s.id)],
    });
    const cash = Number(cashRow.rows[0].cash);
    let positionsValue = 0;
    for (const p of await getPositions(owner)) {
      const bars = cutBars(await getMinuteBars(p.ticker, date), cursor);
      const last = bars.length ? bars[bars.length - 1].close : p.avgPrice;
      positionsValue += last * p.qty;
    }
    const trades = await db.execute({
      sql: "SELECT COUNT(*) AS n FROM executions e JOIN orders o ON o.id = e.order_id WHERE o.owner_type = 'REPLAY' AND o.owner_id = ?",
      args: [Number(s.id)],
    });
    const initial = Number(s.initial_cash);
    const equity = cash + positionsValue;
    result = {
      equity,
      initialCash: initial,
      returnPct: initial > 0 ? (equity / initial - 1) * 100 : 0,
      trades: Number(trades.rows[0].n),
      endedAt: cursor,
    };
    if (body.data.finish) {
      await db.execute({
        sql: "UPDATE replay_sessions SET status = 'FINISHED', result_json = ? WHERE id = ?",
        args: [JSON.stringify(result), Number(s.id)],
      });
    }
  }

  return NextResponse.json({
    cursor,
    fills,
    finished: body.data.finish,
    result,
  });
}
