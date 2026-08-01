import { defineConfig } from "vitest/config";

// e2e/(Playwright)와 분리 — vitest는 lib 단위 테스트만
export default defineConfig({
  test: { include: ["lib/**/*.test.ts"] },
});
