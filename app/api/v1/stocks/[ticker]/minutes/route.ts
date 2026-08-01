// 분봉 조회. 리플레이에서는 session 파라미터를 쓰면 서버가 DB의 세션 커서로
// 잘라서 내려준다 — 클라이언트가 보낸 until은 무시(룩어헤드 차단, 클라이언트 신뢰 금지).
import { NextResponse } from "next/server";
import { z } from "zod";
import { getMinuteBars } from "@/lib/minutes";
import { cutBars } from "@/lib/engine/settle";
import { tradingDb } from "@/lib/db";
import { jerr, qs } from "@/lib/api";

const DATE = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const TS = z.string().regex(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);

export async function GET(req: Request, ctx: { params: Promise<{ ticker: string }> }) {
  const { ticker } = await ctx.params;
  const p = qs(req);
  let date = p.get("date");
  let until = p.get("until");

  const sessionId = p.get("session");
  if (sessionId) {
    const rs = await tradingDb().execute({
      sql: "SELECT date, cursor_ts FROM replay_sessions WHERE id = ?",
      args: [Number(sessionId)],
    });
    if (!rs.rows.length) return jerr("세션 없음", 404);
    date = String(rs.rows[0].date);
    until = rs.rows[0].cursor_ts == null ? null : String(rs.rows[0].cursor_ts);
  }

  if (!date || !DATE.safeParse(date).success) return jerr("date=YYYY-MM-DD 필요");
  if (until && !TS.safeParse(until).success) return jerr("until 형식 오류");

  let bars = await getMinuteBars(ticker, date);
  if (until) bars = cutBars(bars, until);
  return NextResponse.json({ ticker, date, until, bars });
}
