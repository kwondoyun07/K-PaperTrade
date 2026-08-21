// E2E — 실 Turso + 로컬 parquet(005930·000660·034020, 최근 6거래일) 전제.
// APP_PASSWORD 미설정(개발 모드) 기준.
import { expect, test } from "@playwright/test";

test.describe.configure({ mode: "serial" });

test("대시보드 — 계좌·자산 카드·수익률 지표", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("K-PaperTrade").first()).toBeVisible();
  await expect(page.getByText("총자산")).toBeVisible();
  await expect(page.getByText("주문 가능 금액")).toBeVisible();
  // 계좌 셀렉트가 실계좌를 로드했는지
  await expect(page.locator("header select")).toContainText("#");
  // 6단계 스냅샷 시드로 지표 칩이 떠야 함
  await expect(page.getByText("MDD")).toBeVisible();
  await expect(page.getByText("샤프")).toBeVisible();
});

test("종목 검색 → 종목 상세 차트", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder("종목명·코드 검색").fill("034020");
  await page.getByText("두산에너빌리티").click();
  // lightweight-charts가 캔버스를 그렸는지 (숨겨진 대시보드 캔버스 제외)
  await expect(page.locator("canvas:visible").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("투자자별 순매수 (원)")).toBeVisible();
  // 주문 패널
  await expect(page.getByRole("button", { name: /두산에너빌리티 매수/ })).toBeVisible();
});


test("주문·체결 / AI 판단 로그 화면", async ({ page }) => {
  await page.goto("/");
  await page.locator("nav div", { hasText: "주문·체결" }).click();
  await expect(page.getByText("주문·체결 내역")).toBeVisible();
  await page.locator("nav div", { hasText: "AI 판단 로그" }).click();
  await expect(page.getByText(/판단이 맞았는지 채점/)).toBeVisible();
  // 4단계 스모크로 기록된 판단 1건 (숨겨진 화면의 동일 텍스트 제외)
  await expect(page.locator("td:visible", { hasText: "005930" }).first()).toBeVisible();
});

