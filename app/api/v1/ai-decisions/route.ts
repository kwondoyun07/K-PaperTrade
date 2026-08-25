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
  // 이 판단이 실제로 낸 주문. 판단 직후 같은 종목·같은 구분으로 나간 첫 주문인데,
  // 실측 28건이 전부 1~7분 안에 나갔고 판단 사이클은 80분 이상 떨어져 있어
  // 30분 창이면 옆 사이클 것을 잘못 집지 않는다. HOLD는 주문이 없어 항상 NULL.
  const ORDER_LINK =
    "(SELECT o.id FROM orders o WHERE o.owner_type = 'ACCOUNT' AND o.ticker = a.ticker " +
    "   AND o.side = a.action AND o.ordered_at >= a.ts " +
    "   AND o.ordered_at < strftime('%Y-%m-%d %H:%M', a.ts, '+30 minutes') " +
    " ORDER BY o.ordered_at LIMIT 1) AS order_id";
  const rs = ticker
    ? await tradingDb().execute({
        sql: `SELECT a.*, ${ORDER_LINK} FROM ai_decisions a WHERE a.ticker = ? ORDER BY a.ts DESC LIMIT ?`,
        args: [ticker, limit],
      })
    : await tradingDb().execute({
        sql: `SELECT a.*, ${ORDER_LINK} FROM ai_decisions a ORDER BY a.ts DESC LIMIT ?`,
        args: [limit],
      });
  return NextResponse.json({ decisions: rs.rows });
}
