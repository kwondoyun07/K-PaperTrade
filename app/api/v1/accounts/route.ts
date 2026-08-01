import { NextResponse } from "next/server";
import { z } from "zod";
import { tradingDb } from "@/lib/db";
import { jerr, nowKst } from "@/lib/api";

const CreateAccount = z.object({
  name: z.string().min(1).default("기본 계좌"),
  initialCash: z.number().int().positive().default(10_000_000),
});

export async function POST(req: Request) {
  const body = CreateAccount.safeParse(await req.json().catch(() => ({})));
  if (!body.success) return jerr(body.error.issues[0].message);
  const { name, initialCash } = body.data;
  const rs = await tradingDb().execute({
    sql: "INSERT INTO accounts (name, initial_cash, cash, created_at) VALUES (?, ?, ?, ?) RETURNING id",
    args: [name, initialCash, initialCash, nowKst()],
  });
  return NextResponse.json({ id: Number(rs.rows[0].id), name, initialCash }, { status: 201 });
}

export async function GET() {
  const rs = await tradingDb().execute(
    "SELECT id, name, initial_cash, cash, created_at FROM accounts ORDER BY id",
  );
  return NextResponse.json({ accounts: rs.rows });
}
