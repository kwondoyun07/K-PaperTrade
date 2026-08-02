// 분봉 서빙 — 서버 전용.
// 소스 우선순위: 로컬 parquet(개발) → GitHub Release parquet(배포) → Turso 롤링 캐시.
import { readFile } from "node:fs/promises";
import path from "node:path";
import { parquetReadObjects } from "hyparquet";
import { compressors } from "hyparquet-compressors";
import type { Bar } from "@/lib/engine/types";
import { marketDb } from "@/lib/db";

const MINUTE_DIR = process.env.MINUTE_PARQUET_DIR ?? path.join("collector", "data", "minute");
const RELEASE_REPO = process.env.GITHUB_REPO; // 예: "user/K-PaperTrade" — Release parquet 소스
// 비공개 저장소면 필수 (contents:read 스코프). 공개 저장소면 없어도 된다.
const RELEASE_TOKEN = process.env.GITHUB_RELEASE_TOKEN;

// 일자별 전 종목 분봉 캐시: date → (ticker → bars). 최근 3개 일자만 유지.
// ponytail: 일자당 전 종목 인메모리(~70만 행) — 1인용 v1 허용, 병목 시 사전 분할·duckdb로 교체
const cache = new Map<string, Map<string, Bar[]>>();

async function readLocal(date: string): Promise<ArrayBuffer | null> {
  try {
    const b = await readFile(path.join(MINUTE_DIR, `minute-${date}.parquet`));
    return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;
  } catch {
    return null;
  }
}

/** 비공개 저장소: 자산 id를 조회한 뒤 octet-stream으로 내려받는다(공개 URL은 401). */
async function readReleasePrivate(repo: string, tag: string, name: string): Promise<ArrayBuffer | null> {
  const auth = { Authorization: `Bearer ${RELEASE_TOKEN}`, "X-GitHub-Api-Version": "2022-11-28" };
  const rel = await fetch(`https://api.github.com/repos/${repo}/releases/tags/${tag}`, {
    headers: { ...auth, Accept: "application/vnd.github+json" },
  });
  if (!rel.ok) return null;
  const asset = ((await rel.json()) as { assets?: { id: number; name: string }[] }).assets?.find(
    (a) => a.name === name,
  );
  if (!asset) return null;
  const bin = await fetch(`https://api.github.com/repos/${repo}/releases/assets/${asset.id}`, {
    headers: { ...auth, Accept: "application/octet-stream" },
  });
  if (!bin.ok) return null;
  return await bin.arrayBuffer();
}

async function readRelease(date: string): Promise<ArrayBuffer | null> {
  if (!RELEASE_REPO) return null;
  const tag = `minute-${date.slice(0, 7)}`;
  const name = `minute-${date}.parquet`;
  try {
    if (RELEASE_TOKEN) return await readReleasePrivate(RELEASE_REPO, tag, name);
    const r = await fetch(`https://github.com/${RELEASE_REPO}/releases/download/${tag}/${name}`);
    if (!r.ok) return null;
    return await r.arrayBuffer();
  } catch {
    return null;
  }
}

async function loadDate(date: string): Promise<Map<string, Bar[]> | null> {
  const hit = cache.get(date);
  if (hit) return hit;
  const buf = (await readLocal(date)) ?? (await readRelease(date));
  if (!buf) return null;
  const rows = await parquetReadObjects({ file: buf, compressors });
  const byTicker = new Map<string, Bar[]>();
  for (const r of rows) {
    let arr = byTicker.get(String(r.ticker));
    if (!arr) byTicker.set(String(r.ticker), (arr = []));
    arr.push({
      ts: String(r.ts),
      open: Number(r.open),
      high: Number(r.high),
      low: Number(r.low),
      close: Number(r.close),
      volume: Number(r.volume),
    });
  }
  cache.set(date, byTicker);
  for (const k of [...cache.keys()].slice(0, Math.max(0, cache.size - 3))) cache.delete(k);
  return byTicker;
}

export async function getMinuteBars(ticker: string, date: string): Promise<Bar[]> {
  const day = await loadDate(date);
  const bars = day?.get(ticker);
  if (bars?.length) return bars;
  // 폴백: 장중 폴링으로 쌓인 Turso 롤링 캐시
  const rs = await marketDb().execute({
    sql: "SELECT ts, open, high, low, close, volume FROM minute_prices WHERE ticker = ? AND ts LIKE ? ORDER BY ts",
    args: [ticker, `${date}%`],
  });
  return rs.rows.map((r) => ({
    ts: String(r.ts),
    open: Number(r.open),
    high: Number(r.high),
    low: Number(r.low),
    close: Number(r.close),
    volume: Number(r.volume),
  }));
}

export function addDays(date: string, n: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** 전일 종가 — 가격제한폭 ±30% 기준. daily_prices 우선, 없으면 직전 parquet 마지막 종가. */
export async function prevDayClose(ticker: string, date: string): Promise<number | null> {
  const rs = await marketDb().execute({
    sql: "SELECT close FROM daily_prices WHERE ticker = ? AND date < ? ORDER BY date DESC LIMIT 1",
    args: [ticker, date],
  });
  if (rs.rows.length) return Number(rs.rows[0].close);
  for (let i = 1; i <= 7; i++) {
    const bars = (await loadDate(addDays(date, -i)))?.get(ticker);
    if (bars?.length) return bars[bars.length - 1].close;
  }
  return null;
}

/** 최근 종가 (포트폴리오 평가용): daily_prices 최신 → 분봉 캐시 최신 순. */
export async function latestClose(ticker: string): Promise<number | null> {
  const daily = await marketDb().execute({
    sql: "SELECT close FROM daily_prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
    args: [ticker],
  });
  if (daily.rows.length) return Number(daily.rows[0].close);
  const cached = await marketDb().execute({
    sql: "SELECT close FROM minute_prices WHERE ticker = ? ORDER BY ts DESC LIMIT 1",
    args: [ticker],
  });
  return cached.rows.length ? Number(cached.rows[0].close) : null;
}
