// 클라이언트 공용 fetch 헬퍼·타입
import type { Bar } from "@/lib/engine/types";

export async function j<T = Record<string, unknown>>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  const body = (await r.json().catch(() => ({}))) as T & { error?: string };
  if (!r.ok) throw new Error(body.error ?? `HTTP ${r.status}`);
  return body;
}

export const post = <T = Record<string, unknown>>(url: string, body: unknown) =>
  j<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export type StockRow = { ticker: string; name: string; market: string };

// 코드→이름 맵을 세션당 1회 로드해 공유한다. 이름은 부가정보라 실패해도 코드로 폴백.
let namesPromise: Promise<Record<string, string>> | null = null;
export function fetchStockNames(): Promise<Record<string, string>> {
  namesPromise ??= j<{ names: Record<string, string> }>("/api/v1/stocks/names")
    .then((r) => r.names)
    .catch(() => ({}));
  return namesPromise;
}
export type PositionRow = {
  ticker: string;
  qty: number;
  avgPrice: number;
  currentPrice: number;
  value: number;
  pnl: number;
  returnPct: number;
};
export type Portfolio = { cash: number; positions: PositionRow[]; equity: number };
export type OrderRow = {
  id: number;
  ticker: string;
  side: "BUY" | "SELL";
  order_type: "MARKET" | "LIMIT";
  qty: number;
  limit_price: number | null;
  status: string;
  reject_reason: string | null;
  ordered_at: string;
  exec_price: number | null;
  exec_qty: number | null;
  commission: number | null;
  tax: number | null;
  executed_at: string | null;
};

/** 최근 거래일 분봉 탐색 — 오늘부터 최대 lookback일 거슬러 올라가며 첫 데이터 반환 */
export async function fetchLatestMinutes(
  ticker: string,
  lookback = 10,
): Promise<{ date: string; bars: Bar[] } | null> {
  const today = new Date(Date.now() + 9 * 3600_000);
  for (let i = 0; i < lookback; i++) {
    const d = new Date(today);
    d.setUTCDate(d.getUTCDate() - i);
    const date = d.toISOString().slice(0, 10);
    try {
      const r = await j<{ bars: Bar[] }>(`/api/v1/stocks/${ticker}/minutes?date=${date}`);
      if (r.bars.length) return { date, bars: r.bars };
    } catch {
      // 계속 탐색
    }
  }
  return null;
}
