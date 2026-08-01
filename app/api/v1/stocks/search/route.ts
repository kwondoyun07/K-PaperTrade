import { NextResponse } from "next/server";
import { marketDb } from "@/lib/db";
import { jerr, qs } from "@/lib/api";

export async function GET(req: Request) {
  const q = qs(req).get("q")?.trim();
  if (!q) return jerr("q 파라미터 필요");
  const rs = await marketDb().execute({
    sql: "SELECT ticker, name, market FROM stocks WHERE is_active = 1 AND (name LIKE ? OR ticker LIKE ?) ORDER BY ticker LIMIT 20",
    args: [`%${q}%`, `${q}%`],
  });
  return NextResponse.json({ results: rs.rows });
}
