import { describe, expect, it } from "vitest";
import type { Bar } from "./types";
import { DEFAULT_CONFIG, estimateCost, fillOrder } from "./fill";
import { priceLimits, tickSize, validateLimitPrice } from "./rules";

const bar = (open: number, high: number, low: number, close: number, volume = 10_000): Bar => ({
  ts: "2026-07-31 09:01",
  open,
  high,
  low,
  close,
  volume,
});

describe("호가단위", () => {
  it("가격대별 호가단위 표 (2023-01 개편)", () => {
    expect(tickSize(1_999)).toBe(1);
    expect(tickSize(2_000)).toBe(5);
    expect(tickSize(4_995)).toBe(5);
    expect(tickSize(5_000)).toBe(10);
    expect(tickSize(19_990)).toBe(10);
    expect(tickSize(20_000)).toBe(50);
    expect(tickSize(49_950)).toBe(50);
    expect(tickSize(50_000)).toBe(100);
    expect(tickSize(199_900)).toBe(100);
    expect(tickSize(200_000)).toBe(500);
    expect(tickSize(499_500)).toBe(500);
    expect(tickSize(500_000)).toBe(1_000);
  });

  it("지정가 호가단위 검증", () => {
    expect(validateLimitPrice(10_010)).toBeNull();
    expect(validateLimitPrice(10_005)).not.toBeNull(); // 10원 단위 위반
    expect(validateLimitPrice(2_003)).not.toBeNull(); // 5원 단위 위반
    expect(validateLimitPrice(0)).not.toBeNull();
    expect(validateLimitPrice(10_010.5)).not.toBeNull();
  });
});

describe("가격제한폭 ±30%", () => {
  it("상한 내림·하한 올림으로 호가단위 정렬", () => {
    expect(priceLimits(10_000)).toEqual({ up: 13_000, down: 7_000 });
    // 57,300 × 1.3 = 74,490 → 100원 단위 내림 74,400
    // 57,300 × 0.7 = 40,110 → 50원 단위 올림 40,150
    expect(priceLimits(57_300)).toEqual({ up: 74_400, down: 40_150 });
  });
});

describe("시장가 체결 — 다음 분봉 시가 + 슬리피지", () => {
  it("매수: 시가 +5bp, 호가단위 올림", () => {
    const r = fillOrder({ side: "BUY", type: "MARKET", qty: 10 }, bar(10_000, 10_100, 9_950, 10_050), 10_000);
    // 10,000 × 1.0005 = 10,005 → 10원 단위 올림 = 10,010
    expect(r).toMatchObject({ status: "FILLED", fill: { price: 10_010, qty: 10, tax: 0 } });
  });

  it("매도: 시가 −5bp, 호가단위 내림 + 거래세 부과", () => {
    const r = fillOrder({ side: "SELL", type: "MARKET", qty: 10 }, bar(10_000, 10_100, 9_950, 10_050), 10_000);
    if (r.status !== "FILLED") throw new Error(r.status);
    expect(r.fill.price).toBe(9_990); // 9,995 → 내림 9,990
    expect(r.fill.tax).toBe(Math.floor(9_990 * 10 * DEFAULT_CONFIG.sellTaxRate));
    expect(r.fill.tax).toBeGreaterThan(0);
  });

  it("체결가는 시가 기준 — 봉의 종가(미래 정보)와 무관 (룩어헤드 차단)", () => {
    const a = fillOrder({ side: "BUY", type: "MARKET", qty: 1 }, bar(10_000, 12_000, 9_900, 11_900), 10_000);
    const b = fillOrder({ side: "BUY", type: "MARKET", qty: 1 }, bar(10_000, 10_010, 9_400, 9_500), 10_000);
    if (a.status !== "FILLED" || b.status !== "FILLED") throw new Error("expected fills");
    expect(a.fill.price).toBe(b.fill.price); // 시가가 같으면 종가가 달라도 체결가 동일
  });

  it("슬리피지가 상한가를 넘으면 상한가로 클램프", () => {
    // 시가 12,990 < 상한 13,000, +5bp = 12,996.5 → 올림 13,000 → 클램프 13,000
    const r = fillOrder({ side: "BUY", type: "MARKET", qty: 1 }, bar(12_990, 13_000, 12_990, 13_000), 10_000);
    expect(r).toMatchObject({ status: "FILLED", fill: { price: 13_000 } });
  });
});

describe("상·하한가 거부", () => {
  it("상한가 시가 매수 거부, 매도는 허용", () => {
    const limitUpBar = bar(13_000, 13_000, 13_000, 13_000);
    expect(fillOrder({ side: "BUY", type: "MARKET", qty: 1 }, limitUpBar, 10_000)).toEqual({
      status: "REJECTED",
      reason: "상한가",
    });
    expect(fillOrder({ side: "SELL", type: "MARKET", qty: 1 }, limitUpBar, 10_000).status).toBe("FILLED");
  });

  it("하한가 시가 매도 거부, 매수는 허용", () => {
    const limitDownBar = bar(7_000, 7_000, 7_000, 7_000);
    expect(fillOrder({ side: "SELL", type: "MARKET", qty: 1 }, limitDownBar, 10_000)).toEqual({
      status: "REJECTED",
      reason: "하한가",
    });
    expect(fillOrder({ side: "BUY", type: "MARKET", qty: 1 }, limitDownBar, 10_000).status).toBe("FILLED");
  });
});

describe("지정가 체결 — 고가·저가 범위 터치", () => {
  it("매수: 저가가 지정가에 닿지 않으면 PENDING", () => {
    const r = fillOrder({ side: "BUY", type: "LIMIT", qty: 1, limitPrice: 9_900 }, bar(10_000, 10_100, 9_950, 10_050), 10_000);
    expect(r.status).toBe("PENDING");
  });

  it("매수: 터치하면 지정가 체결, 시가가 더 유리하면 시가 체결", () => {
    const touched = fillOrder({ side: "BUY", type: "LIMIT", qty: 1, limitPrice: 10_000 }, bar(10_050, 10_100, 9_990, 10_050), 10_000);
    expect(touched).toMatchObject({ status: "FILLED", fill: { price: 10_000 } });
    const gapDown = fillOrder({ side: "BUY", type: "LIMIT", qty: 1, limitPrice: 10_000 }, bar(9_900, 10_000, 9_880, 9_950), 10_000);
    expect(gapDown).toMatchObject({ status: "FILLED", fill: { price: 9_900 } });
  });

  it("매도: 고가 터치 시 체결, 시가가 더 유리하면 시가 체결", () => {
    const touched = fillOrder({ side: "SELL", type: "LIMIT", qty: 1, limitPrice: 10_100 }, bar(10_000, 10_150, 9_990, 10_050), 10_000);
    expect(touched).toMatchObject({ status: "FILLED", fill: { price: 10_100 } });
    const gapUp = fillOrder({ side: "SELL", type: "LIMIT", qty: 1, limitPrice: 10_100 }, bar(10_200, 10_250, 10_150, 10_200), 10_000);
    expect(gapUp).toMatchObject({ status: "FILLED", fill: { price: 10_200 } });
  });

  it("PENDING 주문은 호출측이 다음 분봉으로 재판정한다 (분봉 1개 단위 판정 = 룩어헤드 불가)", () => {
    const order = { side: "BUY", type: "LIMIT", qty: 1, limitPrice: 9_900 } as const;
    const bar1 = bar(10_000, 10_100, 9_950, 10_050);
    const bar2 = bar(9_950, 9_960, 9_890, 9_900);
    expect(fillOrder(order, bar1, 10_000).status).toBe("PENDING");
    expect(fillOrder(order, bar2, 10_000)).toMatchObject({ status: "FILLED", fill: { price: 9_900 } });
  });

  it("호가단위 위반·가격제한폭 밖 지정가 거부", () => {
    expect(fillOrder({ side: "BUY", type: "LIMIT", qty: 1, limitPrice: 10_005 }, bar(10_000, 10_100, 9_950, 10_050), 10_000)).toEqual({
      status: "REJECTED",
      reason: "호가단위",
    });
    expect(fillOrder({ side: "BUY", type: "LIMIT", qty: 1, limitPrice: 13_500 }, bar(10_000, 10_100, 9_950, 10_050), 10_000)).toEqual({
      status: "REJECTED",
      reason: "가격제한폭",
    });
  });
});

describe("거부 공통", () => {
  it("거래량 0 분봉에서는 체결 불가", () => {
    expect(fillOrder({ side: "BUY", type: "MARKET", qty: 1 }, bar(10_000, 10_000, 10_000, 10_000, 0), 10_000)).toEqual({
      status: "REJECTED",
      reason: "거래량0",
    });
  });

  it("수량 0·음수·소수 거부", () => {
    for (const qty of [0, -1, 1.5]) {
      expect(fillOrder({ side: "BUY", type: "MARKET", qty }, bar(10_000, 10_100, 9_950, 10_050), 10_000)).toEqual({
        status: "REJECTED",
        reason: "수량오류",
      });
    }
  });
});

describe("비용 계산", () => {
  it("수수료 0.015%·거래세 0.15% 원 단위 절사", () => {
    const buy = estimateCost("BUY", 10_000, 100); // 금액 1,000,000
    expect(buy.commission).toBe(150);
    expect(buy.tax).toBe(0);
    expect(buy.total).toBe(1_000_150);

    const sell = estimateCost("SELL", 10_000, 100);
    expect(sell.commission).toBe(150);
    expect(sell.tax).toBe(1_500);
    expect(sell.total).toBe(998_350);
  });

  it("부동소수 경계에서 1원 오차 없음", () => {
    // 820,000 × 0.00015 = 123 — 부동소수로 122.999…가 되어도 123이어야 함
    expect(estimateCost("BUY", 8_200, 100).commission).toBe(123);
  });
});
