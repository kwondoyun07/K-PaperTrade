// KiwoomRestProvider 스텁 (v1 — 서버점검 종료 후 구현).
// 토큰 IP 제약 → Vercel 서버리스에서 직접 주문 금지, Actions 배치에서 처리 (핸드오프 §8).
export function kiwoomNotReady(): never {
  throw new Error("키움 REST API 서버점검 종료 후 구현 (v1)");
}
