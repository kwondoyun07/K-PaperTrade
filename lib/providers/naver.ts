// 네이버 비공식 분봉/시세 프로바이더 (TS, 서버 전용) — 장중 폴링 프록시용.
// 엔드포인트·의미는 collector/providers/naver.py 및 docs/data-pipeline.md와 동일.
// 폴링은 화면에서 보고 있는 종목만 대상(저빈도). 전 종목 폴링 금지.
import type { Bar } from "@/lib/engine/types";

const BASE = "https://api.stock.naver.com/chart/domestic/item";
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36";

export async function fetchMinuteBars(ticker: string, date: string): Promise<Bar[]> {
  const d = date.replaceAll("-", "");
  const url = `${BASE}/${ticker}/minute?periodSizeMinutes=1&startDateTime=${d}0900&endDateTime=${d}1540`;
  const r = await fetch(url, { headers: { "User-Agent": UA }, cache: "no-store" });
  if (!r.ok) throw new Error(`naver HTTP ${r.status}`);
  const data = (await r.json()) as unknown;
  if (!Array.isArray(data)) return [];
  const bars: Bar[] = [];
  for (const item of data as Record<string, unknown>[]) {
    const t = String(item.localDateTime ?? "");
    const close = item.currentPrice;
    if (close == null || t.length < 12) continue;
    const c = Math.round(Number(close));
    const o = item.openPrice == null ? c : Math.round(Number(item.openPrice));
    const h = item.highPrice == null ? Math.max(o, c) : Math.round(Number(item.highPrice));
    const l = item.lowPrice == null ? Math.min(o, c) : Math.round(Number(item.lowPrice));
    bars.push({
      ts: `${t.slice(0, 4)}-${t.slice(4, 6)}-${t.slice(6, 8)} ${t.slice(8, 10)}:${t.slice(10, 12)}`,
      open: o,
      high: h,
      low: l,
      close: c,
      volume: Number(item.accumulatedTradingVolume ?? 0), // 실측: 분당 거래량
    });
  }
  bars.sort((a, b) => (a.ts < b.ts ? -1 : 1));
  return bars;
}
