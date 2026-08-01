import { describe, expect, it } from "vitest";
import { dailyReturns, maxDrawdownPct, sharpeRatio } from "./metrics";

describe("성과 지표", () => {
  it("dailyReturns", () => {
    const r = dailyReturns([100, 110, 99]);
    expect(r).toHaveLength(2);
    expect(r[0]).toBeCloseTo(0.1);
    expect(r[1]).toBeCloseTo(-0.1);
    expect(dailyReturns([100])).toEqual([]);
  });

  it("maxDrawdownPct — 고점 대비 최대 낙폭", () => {
    expect(maxDrawdownPct([100, 120, 90, 130, 104])).toBeCloseTo(25); // 120→90
    expect(maxDrawdownPct([100, 110, 120])).toBe(0); // 낙폭 없음
    expect(maxDrawdownPct([])).toBe(0);
  });

  it("sharpeRatio — 연환산, 엣지 케이스 null", () => {
    expect(sharpeRatio([0.01])).toBeNull(); // 표본 부족
    expect(sharpeRatio([0.01, 0.01, 0.01])).toBeNull(); // 무변동
    const s = sharpeRatio([0.01, -0.005, 0.02, 0.003]);
    expect(s).not.toBeNull();
    expect(s!).toBeGreaterThan(0);
  });
});
