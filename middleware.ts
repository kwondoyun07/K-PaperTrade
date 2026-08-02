// Google 로그인(Auth.js) 게이트.
// AUTH_GOOGLE_ID 미설정 = 로컬 개발 모드 → Auth.js를 아예 호출하지 않는다.
// (auth() 래퍼를 그냥 통과시키면 secret이 없어 요청마다 MissingSecret 에러가 난다)
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
  if (!process.env.AUTH_GOOGLE_ID) return NextResponse.next();
  return (guarded as unknown as (r: NextRequest, c: unknown) => Response)(req, ctx);
}

export const config = { matcher: ["/((?!_next/|favicon).*)"] };
