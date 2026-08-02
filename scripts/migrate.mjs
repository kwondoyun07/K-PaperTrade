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
    try {
      await db.executeMultiple(readFileSync(path.join(dir, f), "utf8"));
      console.log(`${name} ← ${f} 적용 (${url})`);
    } catch (e) {
      // ALTER ADD COLUMN은 IF NOT EXISTS가 없어 재실행 시 중복 컬럼으로 던진다.
      // 그 경우만 이미 적용된 것으로 보고 넘어간다(멱등).
      if (!/duplicate column name/i.test(String(e))) throw e;
      console.log(`${name} ← ${f} 이미 적용됨 (skip)`);
    }
  }
  // owner_email 백필: 소유권 컬럼 도입(002) 전에 만들어진 계좌·세션은 owner_email이
  // NULL이라 소유자조차 접근할 수 없다(guardOwner가 404 → 부트스트랩이 새 계좌를
  // 만들어 기존 계좌를 고아로 만든다). 유일 허용 사용자에게 귀속시킨다. 신규 행은
  // 항상 세션 이메일로 생성되므로 이 UPDATE는 레거시 행만, 사실상 1회만 건드린다(멱등).
  if (name === "trading") {
    const owner = (process.env.ALLOWED_EMAILS ?? "").split(",")[0].trim().toLowerCase();
    if (owner) {
      for (const t of ["accounts", "replay_sessions"]) {
        const r = await db.execute({
          sql: `UPDATE ${t} SET owner_email = ? WHERE owner_email IS NULL`,
          args: [owner],
        });
        if (r.rowsAffected) console.log(`${name} ← ${t} owner_email 백필 ${r.rowsAffected}행 → ${owner}`);
      }
    } else {
      console.log("ALLOWED_EMAILS 미설정 — owner_email 백필 건너뜀");
    }
  }
  db.close();
}
console.log("마이그레이션 완료");
