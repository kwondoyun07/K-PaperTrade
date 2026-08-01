import { describe, expect, it } from "vitest";
import type { Bar } from "./types";
import { addMinutes, cutBars, settlePending } from "./settle";

const bars: Bar[] = [
  { ts: "2026-07-31 09:00", open: 10_000, high: 10_050, low: 9_980, close: 10_020, volume: 100 },
  { ts: "2026-07-31 09:01", open: 10_020, high: 10_060, low: 10_000, close: 10_050, volume: 100 },
  { ts: "2026-07-31 09:02", open: 10_050, high: 10_100, low: 9_950, close: 9_960, volume: 100 },
  { ts: "2026-07-31 09:03", open: 9_960, high: 9_990, low: 9_900, close: 9_950, volume: 100 },
];

describe("cutBars — 서버측 커서 컷", () => {
  it("커서 이후 분봉은 절대 포함되지 않는다", () => {
    const cut = cutBars(bars, "2026-07-31 09:01");
    expect(cut.map((b) => b.ts)).toEqual(["2026-07-31 09:00", "2026-07-31 09:01"]);
    expect(cut.some((b) => b.ts > "2026-07-31 09:01")).toBe(false);
  });

  it("커서가 첫 봉 이전이면 빈 배열", () => {
    expect(cutBars(bars, "2026-07-31 08:59")).toEqual([]);
  });
});

describe("addMinutes", () => {
  it("분 단위 전진 (시·일 경계 포함)", () => {
    expect(addMinutes("2026-07-31 09:00", 1)).toBe("2026-07-31 09:01");
    expect(addMinutes("2026-07-31 09:59", 1)).toBe("2026-07-31 10:00");
    expect(addMinutes("2026-07-31 09:00", 60)).toBe("2026-07-31 10:00");
  });
});

describe("settlePending — 접수 이후 분봉만 사용", () => {
  it("시장가: 접수 직후 '첫' 분봉 시가로만 판정 (다음 1분봉 체결)", () => {
    const r = settlePending({ side: "BUY", type: "MARKET", qty: 1 }, "2026-07-31 09:00", bars, 10_000);
    if (r.status !== "FILLED") throw new Error(r.status);
    // 09:00 접수 → 09:01 봉 시가 10,020 + 5bp = 10,025.01 → 올림 10,030
    expect(r.fill.ts).toBe("2026-07-31 09:01");
    expect(r.fill.price).toBe(10_030);
  });

  it("접수 시각과 같은 분봉(현재 봉)으로는 체결하지 않는다", () => {
    const r = settlePending({ side: "BUY", type: "MARKET", qty: 1 }, "2026-07-31 09:03", bars, 10_000);
    expect(r.status).toBe("PENDING"); // 09:03 이후 봉 없음
  });

  it("지정가: 터치할 때까지 순회 후 체결", () => {
    const r = settlePending(
      { side: "BUY", type: "LIMIT", qty: 1, limitPrice: 9_950 },
      "2026-07-31 09:00",
      bars,
      10_000,
    );
    if (r.status !== "FILLED") throw new Error(r.status);
    expect(r.fill.ts).toBe("2026-07-31 09:02"); // low 9,950 첫 터치
    expect(r.fill.price).toBe(9_950);
  });

  it("커서로 잘린 배열을 주면 잘린 범위 안에서만 판정된다 (룩어헤드 이중 방어)", () => {
    const cut = cutBars(bars, "2026-07-31 09:01"); // 09:02의 터치가 보이지 않음
    const r = settlePending(
      { side: "BUY", type: "LIMIT", qty: 1, limitPrice: 9_950 },
      "2026-07-31 09:00",
      cut,
      10_000,
    );
    expect(r.status).toBe("PENDING");
  });

  it("시장가 거부(상한가)도 첫 분봉에서 즉시 확정", () => {
    const limitUp: Bar[] = [
      { ts: "2026-07-31 09:01", open: 13_000, high: 13_000, low: 13_000, close: 13_000, volume: 50 },
    ];
    const r = settlePending({ side: "BUY", type: "MARKET", qty: 1 }, "2026-07-31 09:00", limitUp, 10_000);
    expect(r).toEqual({ status: "REJECTED", reason: "상한가" });
  });
});
