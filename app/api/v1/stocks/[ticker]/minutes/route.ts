// 분봉 조회. until을 주면 그 시각까지 잘라서 내려준다.
import { NextResponse } from "next/server";
import { z } from "zod";
import { getMinuteBars } from "@/lib/minutes";
import { cutBars } from "@/lib/engine/settle";
import { jerr, qs } from "@/lib/api";

const DATE = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const TS = z.string().regex(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);

export async function GET(req: Request, ctx: { params: Promise<{ ticker: string }> }) {
  const { ticker } = await ctx.params;
  const p = qs(req);
  const date = p.get("date");
  const until = p.get("until");


  if (!date || !DATE.safeParse(date).success) return jerr("date=YYYY-MM-DD 필요");
  if (until && !TS.safeParse(until).success) return jerr("until 형식 오류");

  let bars = await getMinuteBars(ticker, date);
  if (until) bars = cutBars(bars, until);
  return NextResponse.json({ ticker, date, until, bars });
}
