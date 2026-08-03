// 전 종목 코드→이름 맵. 주문·판단 로그는 trading DB, 종목명은 market DB라
// 별도 DB(Turso)라 조인이 안 된다 — 클라이언트가 이 맵을 한 번 받아 코드에 이름을 붙인다.
import { NextResponse } from "next/server";
import { marketDb } from "@/lib/db";

export async function GET() {
  const rs = await marketDb().execute("SELECT ticker, name FROM stocks WHERE is_active = 1");
  const names: Record<string, string> = {};
  for (const r of rs.rows) names[String(r.ticker)] = String(r.name);
  return NextResponse.json({ names });
}
