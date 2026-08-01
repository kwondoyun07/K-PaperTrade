import { NextResponse } from "next/server";
import { getPortfolio } from "@/lib/trading";
import { jerr } from "@/lib/api";

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  try {
    const p = await getPortfolio({ type: "ACCOUNT", id: Number(id) });
    return NextResponse.json(p);
  } catch {
    return jerr("계좌 없음", 404);
  }
}
