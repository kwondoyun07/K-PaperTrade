// 계좌·리플레이 세션 소유권 게이트.
//
// 미들웨어는 "로그인했는가"만 본다. 소유권까지는 각 라우트가 확인해야 한다 —
// 안 하면 로그인한 사용자가 accountId만 바꿔 남의 계좌를 만진다(IDOR).
//
// 두 종류의 호출자가 있다:
//  1) 배치(decide.py·cron/settle) — Google 세션 없이 x-cron-secret으로 호출한다.
//     AI 자동매매·정산은 계좌 소유와 무관하게 돌아야 하므로 전권으로 통과시킨다.
//  2) 사용자 — 세션 이메일이 계좌 소유자와 일치해야 한다.
import { timingSafeEqual } from "node:crypto";
import { auth } from "@/auth";
import { tradingDb } from "@/lib/db";
import { jerr } from "@/lib/api";

function isCron(req: Request): boolean {
  const secret = process.env.CRON_SECRET;
  const given = req.headers.get("x-cron-secret");
  if (!secret || !given) return false;
  const a = Buffer.from(given);
  const b = Buffer.from(secret);
  return a.length === b.length && timingSafeEqual(a, b);
}

export type Caller = { cron: boolean; email: string | null };

export async function caller(req: Request): Promise<Caller> {
  // 로컬·e2e는 미들웨어가 이미 인증을 우회한다(VERCEL 미설정). 세션이 없으므로
  // 여기서도 전권으로 통과시켜야 소유권 검사가 로컬 개발을 막지 않는다.
  if (!process.env.VERCEL) return { cron: true, email: null };
  if (isCron(req)) return { cron: true, email: null };
  const session = await auth();
  return { cron: false, email: session?.user?.email?.toLowerCase() ?? null };
}

// 통과면 null, 막히면 그대로 반환할 응답. 미소유는 존재를 숨기려 404로 통일한다.
export async function guardOwner(
  c: Caller,
  table: "accounts" | "replay_sessions", // 리터럴 유니언 — 사용자 입력 아님(주입 불가)
  id: number,
): Promise<Response | null> {
  if (c.cron) return null;
  if (!c.email) return jerr("인증 필요", 401);
  const rs = await tradingDb().execute({
    sql: `SELECT owner_email FROM ${table} WHERE id = ?`,
    args: [id],
  });
  if (!rs.rows.length) return jerr("없음", 404);
  if (String(rs.rows[0].owner_email ?? "").toLowerCase() !== c.email) return jerr("없음", 404);
  return null;
}
