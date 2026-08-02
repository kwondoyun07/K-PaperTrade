import { NextResponse } from "next/server";
import { getPortfolio } from "@/lib/trading";
import { jerr } from "@/lib/api";
import { caller, guardOwner } from "@/lib/owner";

export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const denied = await guardOwner(await caller(req), "accounts", Number(id));
  if (denied) return denied;
  try {
    const p = await getPortfolio({ type: "ACCOUNT", id: Number(id) });
    return NextResponse.json(p);
  } catch {
    return jerr("계좌 없음", 404);
  }
}
