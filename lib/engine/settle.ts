// 접수된 주문을 분봉 시퀀스에 대해 정산.
// 룩어헤드 이중 방어: 호출측이 커서 이전 봉만 넘기고, 여기서도 접수 시각 이후만 사용.
import type { Bar, EngineConfig, FillResult, OrderReq } from "./types";
import { DEFAULT_CONFIG, fillOrder } from "./fill";

/**
 * 시장가: 접수 직후 첫 분봉에서만 판정(체결 또는 거부).
 * 지정가: 터치할 때까지 봉을 순회, 끝까지 없으면 PENDING 유지.
 */
export function settlePending(
  order: OrderReq,
  orderedAt: string,
  bars: Bar[],
  prevDayClose: number,
  config: EngineConfig = DEFAULT_CONFIG,
): FillResult {
  const candidates = bars.filter((b) => b.ts > orderedAt);
  if (candidates.length === 0) return { status: "PENDING" };
  if (order.type === "MARKET") return fillOrder(order, candidates[0], prevDayClose, config);
  for (const bar of candidates) {
    const r = fillOrder(order, bar, prevDayClose, config);
    if (r.status !== "PENDING") return r;
  }
  return { status: "PENDING" };
}

/** 서버측 커서 컷 — 커서(가상 시각) 이후 분봉은 절대 내려주지 않는다. */
export function cutBars(bars: Bar[], until: string): Bar[] {
  return bars.filter((b) => b.ts <= until);
}

/** 'YYYY-MM-DD HH:MM' + n분 (단순 시계 연산 — 장중 시각 클램프는 호출측) */
export function addMinutes(ts: string, n: number): string {
  const d = new Date(`${ts.replace(" ", "T")}:00Z`);
  d.setUTCMinutes(d.getUTCMinutes() + n);
  return d.toISOString().slice(0, 16).replace("T", " ");
}
