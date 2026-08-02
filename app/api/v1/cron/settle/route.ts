// 배치용 정산 트리거 — 라이브 계좌의 PENDING 주문을 현재까지의 분봉으로 판정한다.
// 인증은 middleware의 x-cron-secret로 통과(Google 세션 없는 무인 잡용).
//
// 서버리스에는 상시 잡이 없어 라이브 주문은 누군가 화면을 열어 폴링할 때만
// 체결되는 구조였다. 이 엔드포인트로 장 마감 후 배치가 일괄 정산할 수 있다.
import { NextResponse } from "next/server";
import { tradingDb } from "@/lib/db";
import { settleOwnerOrders } from "@/lib/trading";

export async function POST() {
  const rs = await tradingDb().execute(
    "SELECT DISTINCT owner_id FROM orders WHERE owner_type = 'ACCOUNT' AND status = 'PENDING'",
  );
  const results = [];
  for (const row of rs.rows) {
    const id = Number(row.owner_id);
    results.push({ accountId: id, fills: await settleOwnerOrders({ type: "ACCOUNT", id }) });
  }
  const filled = results.reduce((n, r) => n + r.fills.filter((f) => f.status === "FILLED").length, 0);
  const rejected = results.reduce((n, r) => n + r.fills.filter((f) => f.status === "REJECTED").length, 0);
  return NextResponse.json({ accounts: results.length, filled, rejected, results });
}
