import { createHash } from "node:crypto";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { z } from "zod";

export async function POST(req: NextRequest) {
  const pw = process.env.APP_PASSWORD;
  if (!pw) return NextResponse.json({ ok: true }); // 개발 모드
  const body = z
    .object({ password: z.string() })
    .safeParse(await req.json().catch(() => null));
  if (!body.success || body.data.password !== pw) {
    return NextResponse.json({ error: "비밀번호가 틀립니다" }, { status: 401 });
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set("k_auth", createHash("sha256").update(pw).digest("hex"), {
    httpOnly: true,
    sameSite: "lax",
    maxAge: 60 * 60 * 24 * 30,
    path: "/",
  });
  return res;
}
