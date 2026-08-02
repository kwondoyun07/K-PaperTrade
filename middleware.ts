// Google 로그인(Auth.js) 게이트.
//
// 우회 조건은 "Google 설정 없음"이 아니라 "로컬 실행"이다(VERCEL 미설정).
// 설정이 없다고 열어주면, 배포 환경에서 env 하나가 빠졌을 때 공개 URL이
// 통째로 무인증으로 열린다 — fail-open은 인증에서 가장 나쁜 실패 방식이다.
// 배포 환경에서는 설정이 잘못돼도 잠기는 쪽으로 실패한다.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { auth } from "@/auth";

const guarded = auth((req) => {
  const path = req.nextUrl.pathname;
  if (path === "/login" || path.startsWith("/api/auth/")) return NextResponse.next();
  if (req.auth) return NextResponse.next();

  if (path.startsWith("/api/")) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  return NextResponse.redirect(new URL("/login", req.url));
});

export default function middleware(req: NextRequest, ctx: unknown) {
  // 로컬 개발·e2e: 인증 없이 통과. Vercel 위에서는 항상 게이트를 태운다.
  if (!process.env.VERCEL) return NextResponse.next();
  return (guarded as unknown as (r: NextRequest, c: unknown) => Response)(req, ctx);
}

export const config = { matcher: ["/((?!_next/|favicon).*)"] };
