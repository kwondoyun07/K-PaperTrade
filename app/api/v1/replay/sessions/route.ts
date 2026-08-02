import { NextResponse } from "next/server";
import { z } from "zod";
import { tradingDb } from "@/lib/db";
import { getMinuteBars } from "@/lib/minutes";
import { jerr, nowKst } from "@/lib/api";
import { caller } from "@/lib/owner";

const CreateSession = z.object({
  name: z.string().optional(),
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  tickers: z.array(z.string().regex(/^\d{6}$/)).min(1).max(10),
  initialCash: z.number().int().positive().default(10_000_000),
});

export async function POST(req: Request) {
  const c = await caller(req);
  if (!c.cron && !c.email) return jerr("인증 필요", 401);
  const body = CreateSession.safeParse(await req.json().catch(() => null));
  if (!body.success) return jerr(body.error.issues[0].message);
  const { name, date, tickers, initialCash } = body.data;

  // 해당 일자 분봉 존재 확인 (parquet/캐시 어디에도 없으면 리플레이 불가)
  const probe = await getMinuteBars(tickers[0], date);
  if (!probe.length) return jerr(`${date} 분봉 데이터 없음 — 백필/수집 여부 확인`);

  const cursor = `${date} 09:00`;
  const rs = await tradingDb().execute({
    sql:
      "INSERT INTO replay_sessions (name, date, tickers, cursor_ts, initial_cash, cash, status, created_at, owner_email) " +
      "VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?) RETURNING id",
    args: [name ?? `${date} 리플레이`, date, JSON.stringify(tickers), cursor, initialCash, initialCash, nowKst(), c.email],
  });
  return NextResponse.json(
    { id: Number(rs.rows[0].id), date, tickers, cursor, initialCash },
    { status: 201 },
  );
}

export async function GET(req: Request) {
  const c = await caller(req);
  const cols =
    "id, name, date, tickers, cursor_ts, initial_cash, cash, status, result_json, created_at";
  if (c.cron) {
    const rs = await tradingDb().execute(
      `SELECT ${cols} FROM replay_sessions ORDER BY id DESC LIMIT 50`,
    );
    return NextResponse.json({ sessions: rs.rows });
  }
  if (!c.email) return jerr("인증 필요", 401);
  const rs = await tradingDb().execute({
    sql: `SELECT ${cols} FROM replay_sessions WHERE owner_email = ? ORDER BY id DESC LIMIT 50`,
    args: [c.email],
  });
  return NextResponse.json({ sessions: rs.rows });
}
