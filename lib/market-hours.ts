// 장시간 판별 유틸 — 클라이언트·서버 공용 순수 함수.
// 공휴일은 판별하지 않는다: 휴일엔 폴링이 빈 응답을 받을 뿐 (과호출 아님).

/** KST 벽시계를 UTC 게터로 읽을 수 있는 Date 표현 */
export function nowKst(): Date {
  return new Date(Date.now() + 9 * 3600_000);
}

export function kstDateStr(d: Date = nowKst()): string {
  return d.toISOString().slice(0, 10);
}

export function kstTsStr(d: Date = nowKst()): string {
  return d.toISOString().slice(0, 16).replace("T", " ");
}

/** 평일 09:00~15:30 KST */
export function isMarketOpen(d: Date = nowKst()): boolean {
  const day = d.getUTCDay();
  if (day === 0 || day === 6) return false;
  const hm = d.getUTCHours() * 60 + d.getUTCMinutes();
  return hm >= 9 * 60 && hm <= 15 * 60 + 30;
}
