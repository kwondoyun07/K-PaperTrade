// 분봉 서빙 — 서버 전용.
// 소스 우선순위: 로컬 parquet(개발) → GitHub Release parquet(배포) → Turso 롤링 캐시.
import { readdir, readFile } from "node:fs/promises";
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
// 실측(2026-08-02, 2,645종목 62만 행/일): 3일자 상주 291MB — Vercel 1GB 안.
// 2일로 줄이면 prevDayClose가 이전 일자를 로드할 때 현재 일자가 밀려나 스래싱한다.
// ponytail: 일자당 전 종목 인메모리 — 1인용 v1 허용, 동시 사용자가 늘면 duckdb/사전 분할로 교체
const cache = new Map<string, Map<string, Bar[]>>();

async function readLocal(date: string): Promise<ArrayBuffer | null> {
  try {
    const b = await readFile(path.join(MINUTE_DIR, `minute-${date}.parquet`));
    return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;
  } catch {
    return null;
  }
}

const ghHeaders = (accept: string) => ({
  Accept: accept,
  "X-GitHub-Api-Version": "2022-11-28",
  ...(RELEASE_TOKEN ? { Authorization: `Bearer ${RELEASE_TOKEN}` } : {}),
});

/** 릴리스 자산 목록 (다운로드 없이 메타데이터만) */
async function releaseAssets(tag: string): Promise<{ id: number; name: string }[]> {
  if (!RELEASE_REPO) return [];
  try {
    const r = await fetch(`https://api.github.com/repos/${RELEASE_REPO}/releases/tags/${tag}`, {
      headers: ghHeaders("application/vnd.github+json"),
    });
    if (!r.ok) return [];
    return ((await r.json()) as { assets?: { id: number; name: string }[] }).assets ?? [];
  } catch {
    return [];
  }
}

/** 비공개 저장소: 자산 id를 조회한 뒤 octet-stream으로 내려받는다(공개 URL은 404). */
async function readReleasePrivate(repo: string, tag: string, name: string): Promise<ArrayBuffer | null> {
  const asset = (await releaseAssets(tag)).find((a) => a.name === name);
  if (!asset) return null;
  const bin = await fetch(`https://api.github.com/repos/${repo}/releases/assets/${asset.id}`, {
    headers: ghHeaders("application/octet-stream"),
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
  // 파일이 "없음"과 "읽을 수 없음"을 똑같이 null로 흘려보내 Turso 캐시 폴백을 타게 한다.
  // 수집기가 쓰는 중인 parquet는 footer가 없어 파싱이 실패하는데, 여기서 안 잡으면
  // 분봉·리플레이·주문 라우트가 전부 500이 된다.
  let rows: Record<string, unknown>[];
  try {
    rows = await parquetReadObjects({ file: buf, compressors });
  } catch (e) {
    console.error(`parquet 파싱 실패(${date}) — Turso 캐시로 폴백`, e);
    return null;
  }
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

const DATE_RE = /^minute-(\d{4}-\d{2}-\d{2})\.parquet$/;

/**
 * 리플레이 가능한 일자 목록 (최신순).
 * 파일 "존재"만 보므로 parquet를 열지 않는다 — 일자별로 분봉을 조회해 확인하면
 * 전 종목 파일(62만 행)을 일자마다 파싱하게 되어 화면 진입이 수십 초 걸린다.
 */
export async function listMinuteDates(limit = 6): Promise<string[]> {
  const dates = new Set<string>();
  try {
    for (const f of await readdir(MINUTE_DIR)) {
      const m = DATE_RE.exec(f);
      if (m) dates.add(m[1]);
    }
  } catch {
    // 로컬 디렉토리 없음 — Release만 사용
  }
  if (RELEASE_REPO) {
    // 분봉 보관은 롤링이라 이번 달·지난 달 태그면 충분
    const now = new Date(Date.now() + 9 * 3600_000);
    const y = now.getUTCFullYear();
    const m = now.getUTCMonth();
    const tags = [
      new Date(Date.UTC(y, m, 1)),
      new Date(Date.UTC(y, m - 1, 1)),
    ].map((d) => `minute-${d.toISOString().slice(0, 7)}`);
    for (const tag of tags) {
      for (const a of await releaseAssets(tag)) {
        const mm = DATE_RE.exec(a.name);
        if (mm) dates.add(mm[1]);
      }
    }
  }
  return [...dates].sort().reverse().slice(0, limit);
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
