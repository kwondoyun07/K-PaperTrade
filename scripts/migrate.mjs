// 마이그레이션 적용: db/migrations/<db>/*.sql 을 순서대로 executeMultiple.
// TURSO_* env가 있으면 원격 Turso, 없으면 로컬 파일 DB(.data/)에 적용한다.
// 사용: pnpm migrate
import { createClient } from "@libsql/client";
import { existsSync, mkdirSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";

// 의존성 없는 간단 .env 로더
if (existsSync(".env")) {
  for (const line of readFileSync(".env", "utf8").split(/\r?\n/)) {
    const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (m && process.env[m[1]] === undefined) process.env[m[1]] = m[2].trim();
  }
}

mkdirSync(".data", { recursive: true });

const DBS = [
  ["krx_market", process.env.TURSO_KRX_MARKET_URL ?? "file:.data/krx_market.db", process.env.TURSO_KRX_MARKET_AUTH_TOKEN],
  ["trading", process.env.TURSO_TRADING_URL ?? "file:.data/trading.db", process.env.TURSO_TRADING_AUTH_TOKEN],
];

for (const [name, url, authToken] of DBS) {
  const db = createClient({ url, authToken });
  const dir = path.join("db", "migrations", name);
  for (const f of readdirSync(dir).sort()) {
    await db.executeMultiple(readFileSync(path.join(dir, f), "utf8"));
    console.log(`${name} ← ${f} 적용 (${url})`);
  }
  db.close();
}
console.log("마이그레이션 완료");
