// 리플레이 가능한 일자 목록 — parquet 존재 여부만 확인(파싱 없음).
import { NextResponse } from "next/server";
import { listMinuteDates } from "@/lib/minutes";
import { qs } from "@/lib/api";

export async function GET(req: Request) {
  const limit = Math.min(Number(qs(req).get("limit") ?? 6), 30);
  return NextResponse.json({ dates: await listMinuteDates(limit) });
}
