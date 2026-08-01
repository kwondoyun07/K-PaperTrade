// 1인용 단일 비밀번호 세션 (APP_PASSWORD).
// 다중 사용자 확장 시: 이 파일과 app/api/auth/login을 Auth.js로 교체하는 것이 훅.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

async function sha256Hex(s: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(d))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function middleware(req: NextRequest) {
  const pw = process.env.APP_PASSWORD;
  if (!pw) return NextResponse.next(); // 미설정 = 로컬 개발 모드 (인증 생략)
  const path = req.nextUrl.pathname;
  if (path === "/login" || path === "/api/auth/login") return NextResponse.next();
  if (req.cookies.get("k_auth")?.value === (await sha256Hex(pw))) {
    return NextResponse.next();
  }
  if (path.startsWith("/api/")) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  return NextResponse.redirect(new URL("/login", req.url));
}

export const config = { matcher: ["/((?!_next/|favicon).*)"] };
