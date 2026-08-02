// Auth.js v5 — Google 로그인. 1인용이므로 이메일 allowlist로 잠근다.
//
// 로컬 개발: AUTH_GOOGLE_ID가 없으면 middleware가 인증을 건너뛴다(e2e·dev 편의).
// 배포: ALLOWED_EMAILS가 비어 있으면 **아무도 못 들어온다**(fail-closed).
// 공개 URL이라 allowlist가 비었을 때 전체 허용으로 열어두면 누구나 남의 계좌를
// 만지게 되므로, 잠기는 쪽이 맞다.
import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

const allowed = (process.env.ALLOWED_EMAILS ?? "")
  .split(",")
  .map((s) => s.trim().toLowerCase())
  .filter(Boolean);

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google],
  pages: { signIn: "/login", error: "/login" },
  callbacks: {
    signIn({ profile }) {
      const email = profile?.email?.toLowerCase();
      if (!email || !profile?.email_verified) return false;
      return allowed.includes(email);
    },
  },
});
