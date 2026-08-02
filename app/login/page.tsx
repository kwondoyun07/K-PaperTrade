import { redirect } from "next/navigation";
import { auth, signIn } from "@/auth";
import { UP } from "@/lib/format";

export default async function Login({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  if (await auth()) redirect("/");
  const configured = !!process.env.AUTH_GOOGLE_ID;

  return (
    <main style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="card" style={{ padding: 28, width: 340, display: "flex", flexDirection: "column", gap: 16, alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 26, height: 26, borderRadius: 8, background: UP, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 13, color: "#fff" }}>
            K
          </div>
          <span style={{ fontWeight: 700, fontSize: 16 }}>K-PaperTrade</span>
        </div>
        <span style={{ fontSize: 12, color: "#8B8D98", textAlign: "center", lineHeight: 1.6 }}>
          국내주식 1분봉 모의투자
          <br />
          허용된 계정만 로그인할 수 있습니다
        </span>

        {error && (
          <span style={{ fontSize: 12, color: UP, textAlign: "center" }}>
            {error === "AccessDenied"
              ? "허용되지 않은 계정입니다"
              : "로그인에 실패했습니다. 다시 시도해 주세요"}
          </span>
        )}

        {!configured && (
          <span style={{ fontSize: 12, color: "#E8C55A", textAlign: "center", lineHeight: 1.6 }}>
            Google 로그인이 아직 설정되지 않았습니다.
            <br />
            AUTH_GOOGLE_ID·AUTH_GOOGLE_SECRET을 등록해 주세요.
          </span>
        )}

        <form
          style={{ width: "100%" }}
          action={async () => {
            "use server";
            await signIn("google", { redirectTo: "/" });
          }}
        >
          <button
            type="submit"
            disabled={!configured}
            style={{
              width: "100%", height: 42, borderRadius: 10, border: "1px solid #2C2C36",
              background: "#fff", color: "#1a1a1a", fontSize: 14, fontWeight: 600,
              cursor: configured ? "pointer" : "not-allowed", opacity: configured ? 1 : 0.5,
              display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
            }}
          >
            <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
              <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.7 30.1 0 24 0 14.6 0 6.4 5.4 2.5 13.2l7.8 6.1C12.2 13.2 17.6 9.5 24 9.5z" />
              <path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9.1h12.4c-.5 2.9-2.1 5.3-4.6 6.9l7.1 5.5c4.2-3.9 6.6-9.6 6.6-16.4z" />
              <path fill="#FBBC05" d="M10.3 28.7c-.5-1.4-.8-2.9-.8-4.5s.3-3.1.8-4.5l-7.8-6.1C.9 16.7 0 20.2 0 24s.9 7.3 2.5 10.4l7.8-5.7z" />
              <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.1-5.5c-2 1.3-4.5 2.1-8.8 2.1-6.4 0-11.8-3.7-13.7-8.9l-7.8 5.7C6.4 42.6 14.6 48 24 48z" />
            </svg>
            Google로 로그인
          </button>
        </form>
      </div>
    </main>
  );
}
