// 체결 엔진 — 순수 함수. 룩어헤드 금지 설계:
// 주문 1건을 "주문 접수 직후의 분봉 1개"에 대해서만 판정한다. 미래 분봉은
// 시그니처상 입력받을 수 없다. 지정가가 PENDING이면 호출측(리플레이 틱/라이브
// 폴링)이 그다음 분봉으로 다시 호출한다.
//
// v1 범위 밖(미구현): VI(변동성완화장치), 동시호가, 공매도.
// 거래정지·관리종목·상장폐지 필터는 API 레벨(stocks.is_active)에서 처리.
// 참고: HKUDS/Vibe-Trading KRX 백테스트 엔진 — 체결 시점에 ±30% 판정.

import type { Bar, EngineConfig, FillResult, OrderReq, Side } from "./types";
import { priceLimits, roundDownToTick, roundUpToTick, validateLimitPrice } from "./rules";

export const DEFAULT_CONFIG: EngineConfig = {
  slippageBp: 5,
  commissionRate: 0.00015, // 수수료 0.015%
  sellTaxRate: 0.0015, // 증권거래세+농특세 0.15% (2026-08 기준, env로 조정)
};

// 부동소수 오차로 정수 경계에서 1원 어긋나는 것 방지 (예: rate*amount = 122.999…97)
const EPS = 1e-9;

export function estimateCost(
  side: Side,
  price: number,
  qty: number,
  config: EngineConfig = DEFAULT_CONFIG,
): { amount: number; commission: number; tax: number; total: number } {
  const amount = price * qty;
  const commission = Math.floor(amount * config.commissionRate + EPS);
  const tax = side === "SELL" ? Math.floor(amount * config.sellTaxRate + EPS) : 0;
  const total = side === "BUY" ? amount + commission : amount - commission - tax;
  return { amount, commission, tax, total };
}

/**
 * 주문을 다음 분봉(nextBar)에 대해 판정한다.
 *
 * - 시장가: nextBar 시가 + 슬리피지(bp), 호가단위 절사(매수 올림/매도 내림),
 *   가격제한폭 내로 클램프
 * - 지정가: nextBar 고가·저가 범위에 지정가가 닿으면 체결
 *   (시가가 지정가보다 유리하면 시가 체결), 아니면 PENDING
 * - 상한가 시가 매수 거부 / 하한가 시가 매도 거부, 거래량 0 거부
 */
export function fillOrder(
  order: OrderReq,
  nextBar: Bar,
  prevDayClose: number,
  config: EngineConfig = DEFAULT_CONFIG,
): FillResult {
  if (!Number.isInteger(order.qty) || order.qty <= 0) {
    return { status: "REJECTED", reason: "수량오류" };
  }
  if (nextBar.volume <= 0) {
    return { status: "REJECTED", reason: "거래량0" };
  }
  const { up, down } = priceLimits(prevDayClose);
  if (order.side === "BUY" && nextBar.open >= up) {
    return { status: "REJECTED", reason: "상한가" };
  }
  if (order.side === "SELL" && nextBar.open <= down) {
    return { status: "REJECTED", reason: "하한가" };
  }

  let price: number;
  if (order.type === "MARKET") {
    const slip = 1 + (config.slippageBp / 10_000) * (order.side === "BUY" ? 1 : -1);
    price =
      order.side === "BUY"
        ? Math.min(roundUpToTick(nextBar.open * slip), up)
        : Math.max(roundDownToTick(nextBar.open * slip), down);
  } else {
    const limit = order.limitPrice;
    if (limit == null) return { status: "REJECTED", reason: "지정가없음" };
    if (validateLimitPrice(limit) !== null) return { status: "REJECTED", reason: "호가단위" };
    if (limit > up || limit < down) return { status: "REJECTED", reason: "가격제한폭" };
    if (order.side === "BUY") {
      if (nextBar.low > limit) return { status: "PENDING" };
      price = Math.min(nextBar.open, limit);
    } else {
      if (nextBar.high < limit) return { status: "PENDING" };
      price = Math.max(nextBar.open, limit);
    }
  }

  const { commission, tax } = estimateCost(order.side, price, order.qty, config);
  return {
    status: "FILLED",
    fill: { price, qty: order.qty, commission, tax, ts: nextBar.ts },
  };
}
