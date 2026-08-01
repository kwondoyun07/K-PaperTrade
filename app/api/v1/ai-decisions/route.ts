import { NextResponse } from "next/server";
import { z } from "zod";
import { tradingDb } from "@/lib/db";
import { jerr, qs } from "@/lib/api";

const CreateDecision = z.object({
  ticker: z.string().regex(/^\d{6}$/),
  ts: z.string().regex(/^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?$/),
  action: z.enum(["BUY", "SELL", "HOLD"]),
  reasonSummary: z.string().optional(),
  source: z.string().optional(),
  brokerOrderId: z.string().optional(), // v1.5 키움 미러링 대사용
});

export async function POST(req: Request) {
  const body = CreateDecision.safeParse(await req.json().catch(() => null));
  if (!body.success) return jerr(body.error.issues[0].message);
  const d = body.data;
  const rs = await tradingDb().execute({
    sql: "INSERT INTO ai_decisions (ticker, ts, action, reason_summary, source, broker_order_id) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
    args: [d.ticker, d.ts, d.action, d.reasonSummary ?? null, d.source ?? null, d.brokerOrderId ?? null],
  });
  return NextResponse.json({ id: Number(rs.rows[0].id) }, { status: 201 });
}

export async function GET(req: Request) {
  const p = qs(req);
  const ticker = p.get("ticker");
  const limit = Math.min(Number(p.get("limit") ?? 50), 200);
  const rs = ticker
    ? await tradingDb().execute({
        sql: "SELECT * FROM ai_decisions WHERE ticker = ? ORDER BY ts DESC LIMIT ?",
        args: [ticker, limit],
      })
    : await tradingDb().execute({
        sql: "SELECT * FROM ai_decisions ORDER BY ts DESC LIMIT ?",
        args: [limit],
      });
  return NextResponse.json({ decisions: rs.rows });
}
