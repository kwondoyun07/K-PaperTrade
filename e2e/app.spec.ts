// E2E — 실 Turso + 로컬 parquet(005930·000660·034020, 최근 6거래일) 전제.
// APP_PASSWORD 미설정(개발 모드) 기준. 리플레이 주문→체결은 실제 서버 세션으로 검증.
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

test("리플레이 — 세션 생성·재생·주문·체결까지", async ({ page }) => {
  await page.goto("/");
  await page.locator("nav div", { hasText: "리플레이" }).click();

  // 세션 자동 생성 대기 (재생 버튼 활성화)
  const play = page.getByRole("button", { name: /재생/ });
  await expect(play).toBeEnabled({ timeout: 20_000 });

  // 재생 시작 → 가상 시계가 09:00에서 전진
  await play.click();
  await expect(page.locator("text=/^09:00$/")).toHaveCount(0, { timeout: 15_000 });

  // 시장가 매수 1주 → 다음 tick에서 체결
  const qty = page.locator('input[placeholder="0"]:visible');
  await qty.fill("1");
  await page.locator("button:visible", { hasText: /매수$/ }).last().click();

  // "주문 접수" 토스트는 단언하지 않는다 — 10x 배속에서 450ms 뒤 tick이 돌아
  // 체결 토스트로 교체되므로 태생적으로 레이스다. 결과(체결·보유)만 확인한다.
  await expect(page.getByText(/매수 체결 · 1주/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/1주 · 평단/)).toBeVisible({ timeout: 30_000 });
});

test("주문·체결 / AI 판단 로그 화면", async ({ page }) => {
  await page.goto("/");
  await page.locator("nav div", { hasText: "주문·체결" }).click();
  await expect(page.getByText("주문·체결 내역")).toBeVisible();
  await page.locator("nav div", { hasText: "AI 판단 로그" }).click();
  await expect(page.getByText(/판단 이후 수익률/)).toBeVisible();
  // 4단계 스모크로 기록된 판단 1건 (숨겨진 화면의 동일 텍스트 제외)
  await expect(page.locator("td:visible", { hasText: "005930" }).first()).toBeVisible();
});

test("API 룩어헤드 가드 — 세션 커서 밖 분봉 미노출", async ({ request }) => {
  const created = await request.post("/api/v1/replay/sessions", {
    data: { date: "2026-07-30", tickers: ["005930"], name: "e2e-lookahead" },
  });
  expect(created.status()).toBe(201);
  const { id } = await created.json();
  // 위조 until을 줘도 서버 커서(09:00)로 잘려야 함
  const r = await request.get(`/api/v1/stocks/005930/minutes?session=${id}&until=2026-07-30 15:00`);
  const body = await r.json();
  expect(body.until).toBe("2026-07-30 09:00");
  for (const b of body.bars) {
    expect(b.ts <= "2026-07-30 09:00").toBeTruthy();
  }
});
