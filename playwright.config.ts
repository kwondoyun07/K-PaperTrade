import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  // dev 서버는 라우트를 첫 요청 때 컴파일한다(실측 3~8초) + Turso 왕복이 서울 리전.
  // 기본 5초로는 첫 화면 단언이 콜드 스타트에서 실패한다.
  expect: { timeout: 20_000 },
  fullyParallel: false, // 리플레이 세션 등 공유 상태 — 순차 실행
  workers: 1,
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "pnpm dev",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
