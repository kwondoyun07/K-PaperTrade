// 외부 스케줄러(cron-job.org)가 GitHub 워크플로를 정시에 깨우는 통로.
//
// GitHub의 schedule 트리거는 큐를 타서 밀린다. 8/26까지는 30~70분이었는데 8/27부터
// 10~11시간으로 악화돼 이틀 연속 장중 실행이 0회였다(8/28엔 SELL 판단 3건이
// 22:04에 나 주문이 통째로 없었다). 반면 workflow_dispatch는 큐를 안 타고 즉시
// 러너를 잡는다 — 수동 트리거가 생성 29초 만에 시작한 것으로 확인했다.
//
// PAT를 외부 서비스에 맡기지 않으려고 한 단계를 둔다: cron-job.org는 x-cron-secret만
// 들고 여기를 때리고, GitHub 토큰은 Vercel 환경변수에만 있다.
import { NextResponse } from "next/server";
import { jerr, qs } from "@/lib/api";

const REPO = process.env.GITHUB_REPO ?? "kwondoyun07/K-PaperTrade";

// 허용 목록. 이 엔드포인트가 뚫려도 임의 워크플로를 돌릴 수 없게 한다.
// mirror는 뺐다 — 실주문을 쏘는 워크플로라 "사람 확인을 거치도록" 스케줄 없이
// workflow_dispatch만 두게 설계돼 있다. 자동으로 깨우면 그 전제가 깨진다.
// 둘 다 필수 입력이 없어 {"ref":"main"}만으로 dispatch된다(mirror는 account_id 필수).
const ALLOWED = new Set(["decide", "collect"]);

export async function POST(req: Request) {
  // 인증은 middleware의 x-cron-secret이 이미 통과시킨 것이지만, 로컬(VERCEL 없음)에선
  // 게이트가 통째로 꺼져 있어 여기서 한 번 더 본다.
  const secret = process.env.CRON_SECRET;
  if (secret && req.headers.get("x-cron-secret") !== secret) return jerr("인증 필요", 401);

  const name = qs(req).get("workflow") ?? "decide";
  if (!ALLOWED.has(name)) return jerr(`허용되지 않은 워크플로: ${name}`, 400);

  // 이미 등록된 릴리스 토큰을 폴백으로 쓴다. 같은 리포·같은 소유자라 신뢰 경계가
  // 같고, 권한이 모자라면 GitHub가 403으로 알려준다. 그때만 전용 PAT를 발급하면 된다.
  const token = process.env.GITHUB_DISPATCH_TOKEN || process.env.GITHUB_RELEASE_TOKEN;
  if (!token) return jerr("GITHUB_DISPATCH_TOKEN 미설정", 500);

  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${name}.yml/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: "main" }),
  });

  // GitHub는 성공 시 204(본문 없음). 실패 본문은 그대로 흘리지 않는다 — 토큰 관련
  // 메시지가 섞일 수 있어 상태 코드만 돌려준다.
  if (r.status !== 204) {
    return jerr(`GitHub 응답 ${r.status}`, r.status === 401 || r.status === 403 ? 502 : 500);
  }
  return NextResponse.json({ triggered: name, at: new Date().toISOString() });
}
