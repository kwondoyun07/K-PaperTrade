// 더미 데이터 시뮬레이션 — 2단계(실데이터 수집)·5단계(실데이터 연결) 전까지 화면 전용.
// 시드 기반 결정적 생성이라 같은 종목·날짜는 항상 같은 차트가 나온다.

export type Bar = { o: number; h: number; l: number; c: number; v: number };
export type Stock = { code: string; name: string; base: number; limitUp?: boolean };

export const START_CASH = 10_000_000;
export const FEE_RATE = 0.00015; // 수수료 0.015%
export const SELL_TAX_RATE = 0.0015; // 증권거래세+농특세 0.15% (2026-08 기준, 변동 시 수정)

export const STOCKS: Stock[] = [
  { code: "005930", name: "삼성전자", base: 71800 },
  { code: "000660", name: "SK하이닉스", base: 198500 },
  { code: "035420", name: "NAVER", base: 187300 },
  { code: "035720", name: "카카오", base: 48950 },
  { code: "086520", name: "에코프로", base: 104200, limitUp: true },
  { code: "068270", name: "셀트리온", base: 178900 },
  { code: "005380", name: "현대차", base: 242000 },
  { code: "034020", name: "두산에너빌리티", base: 17840 },
];

export const HOLDINGS: { code: string; qty: number; avg: number }[] = [
  { code: "005930", qty: 120, avg: 69500 },
  { code: "000660", qty: 15, avg: 185000 },
  { code: "035420", qty: 20, avg: 192400 },
  { code: "035720", qty: 150, avg: 52300 },
];

export const FILLS: { side: "매수" | "매도"; name: string; detail: string; time: string }[] = [
  { side: "매수", name: "삼성전자", detail: "20주 · ₩71,300", time: "07-31 14:52" },
  { side: "매도", name: "카카오", detail: "50주 · ₩49,150", time: "07-31 13:10" },
  { side: "매수", name: "SK하이닉스", detail: "5주 · ₩197,800", time: "07-31 10:44" },
  { side: "매수", name: "카카오", detail: "80주 · ₩48,600", time: "07-30 15:02" },
  { side: "매도", name: "두산에너빌리티", detail: "110주 · ₩18,020", time: "07-30 09:31" },
];

function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function seedOf(str: string) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

const cache: Record<string, Bar[]> = {};

// 09:00~15:30 → 391개 1분봉
export function series(code: string, date: string): Bar[] {
  const key = code + date;
  if (cache[key]) return cache[key];
  const st = STOCKS.find((s) => s.code === code)!;
  const r = rng(seedOf(key));
  const tick = st.base > 100000 ? 100 : st.base > 20000 ? 50 : 10;
  const out: Bar[] = [];
  let px = st.base * (0.985 + r() * 0.03);
  const rd = (n: number) => Math.round(n / tick) * tick;
  for (let i = 0; i < 391; i++) {
    const drift = Math.sin(i / 60 + r() * 2) * 0.0004;
    const vol = 0.0012 + (i < 30 || i > 360 ? 0.0012 : 0);
    const o = px;
    px = px * (1 + drift + (r() - 0.5) * 2 * vol);
    const hi = Math.max(o, px) * (1 + r() * vol);
    const lo = Math.min(o, px) * (1 - r() * vol);
    out.push({
      o: rd(o),
      c: rd(px),
      h: rd(hi),
      l: rd(lo),
      v: Math.round((r() * 0.8 + 0.2) * (i < 30 || i > 360 ? 32000 : 9000)),
    });
  }
  cache[key] = out;
  return out;
}

export function curve(seed: number, n: number, drift: number, vol: number): number[] {
  const r = rng(seed);
  const out = [0];
  let v = 0;
  for (let i = 1; i < n; i++) {
    v += drift + (r() - 0.5) * vol;
    out.push(v);
  }
  return out;
}
