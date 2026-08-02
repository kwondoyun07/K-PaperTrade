import { NextResponse } from "next/server";
import { z } from "zod";
import { tradingDb } from "@/lib/db";
import { jerr, nowKst } from "@/lib/api";
import { caller } from "@/lib/owner";

const CreateAccount = z.object({
  name: z.string().min(1).default("기본 계좌"),
  initialCash: z.number().int().positive().default(10_000_000),
});

const COLS = "id, name, initial_cash, cash, created_at";

export async function POST(req: Request) {
  const c = await caller(req);
  if (!c.cron && !c.email) return jerr("인증 필요", 401);
  const body = CreateAccount.safeParse(await req.json().catch(() => ({})));
  if (!body.success) return jerr(body.error.issues[0].message);
  const { name, initialCash } = body.data;
  const rs = await tradingDb().execute({
    sql: "INSERT INTO accounts (name, initial_cash, cash, created_at, owner_email) VALUES (?, ?, ?, ?, ?) RETURNING id",
    args: [name, initialCash, initialCash, nowKst(), c.email],
  });
  return NextResponse.json({ id: Number(rs.rows[0].id), name, initialCash }, { status: 201 });
}

export async function GET(req: Request) {
  const c = await caller(req);
  // 배치는 전 계좌, 사용자는 자기 계좌만. 필터가 없으면 남의 계좌가 목록에 새어나간다.
  if (c.cron) {
    const rs = await tradingDb().execute(`SELECT ${COLS} FROM accounts ORDER BY id`);
    return NextResponse.json({ accounts: rs.rows });
  }
  if (!c.email) return jerr("인증 필요", 401);
  const rs = await tradingDb().execute({
    sql: `SELECT ${COLS} FROM accounts WHERE owner_email = ? ORDER BY id`,
    args: [c.email],
  });
  return NextResponse.json({ accounts: rs.rows });
}
