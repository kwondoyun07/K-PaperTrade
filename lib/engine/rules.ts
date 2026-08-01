// KRX 시장 규칙 상수·유틸 (호가단위, 가격제한폭)

// 호가단위 (2023-01 개편): [미만 상한, 호가단위]
const TICK_TABLE: readonly (readonly [number, number])[] = [
  [2_000, 1],
  [5_000, 5],
  [20_000, 10],
  [50_000, 50],
  [200_000, 100],
  [500_000, 500],
  [Infinity, 1_000],
];

export function tickSize(price: number): number {
  for (const [upper, tick] of TICK_TABLE) {
    if (price < upper) return tick;
  }
  return 1_000;
}

export function roundDownToTick(price: number): number {
  const t = tickSize(price);
  return Math.floor(price / t) * t;
}

export function roundUpToTick(price: number): number {
  const t = tickSize(price);
  return Math.ceil(price / t) * t;
}

/** 지정가 검증 — 위반 사유 문자열, 정상이면 null */
export function validateLimitPrice(price: number): string | null {
  if (!Number.isInteger(price) || price <= 0) return "가격이 올바르지 않음";
  const t = tickSize(price);
  if (price % t !== 0) return `호가단위(${t}원) 위반`;
  return null;
}

/** 가격제한폭 ±30% (전일 종가 기준). 상한은 내림, 하한은 올림으로 호가단위 정렬 */
export function priceLimits(prevDayClose: number): { up: number; down: number } {
  return {
    up: roundDownToTick(prevDayClose * 1.3),
    down: roundUpToTick(prevDayClose * 0.7),
  };
}
