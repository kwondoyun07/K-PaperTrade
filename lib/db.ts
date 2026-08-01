// Turso(libSQL) 클라이언트 — 서버 전용. NEXT_PUBLIC_ 노출 금지.
// TURSO_* env 미설정이면 로컬 파일 DB(.data/)로 폴백해 개발이 막히지 않게 한다.
import { createClient, type Client } from "@libsql/client";

function make(urlEnv: string, tokenEnv: string, fileFallback: string): Client {
  const url = process.env[urlEnv];
  return createClient(
    url ? { url, authToken: process.env[tokenEnv] } : { url: fileFallback },
  );
}

let _market: Client | undefined;
let _trading: Client | undefined;

export const marketDb = (): Client =>
  (_market ??= make("TURSO_KRX_MARKET_URL", "TURSO_KRX_MARKET_AUTH_TOKEN", "file:.data/krx_market.db"));

export const tradingDb = (): Client =>
  (_trading ??= make("TURSO_TRADING_URL", "TURSO_TRADING_AUTH_TOKEN", "file:.data/trading.db"));
