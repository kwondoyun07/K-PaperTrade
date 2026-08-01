// 성과 지표 — 순수 함수 (performance 라우트에서 사용)

/** 일별 수익률 (fraction). equity 길이 n → n-1개 */
export function dailyReturns(equity: number[]): number[] {
  const out: number[] = [];
  for (let i = 1; i < equity.length; i++) {
    out.push(equity[i - 1] > 0 ? equity[i] / equity[i - 1] - 1 : 0);
  }
  return out;
}

/** 최대 낙폭 % (양수로 반환, 낙폭 없으면 0) */
export function maxDrawdownPct(equity: number[]): number {
  let peak = -Infinity;
  let mdd = 0;
  for (const v of equity) {
    peak = Math.max(peak, v);
    if (peak > 0) mdd = Math.max(mdd, (1 - v / peak) * 100);
  }
  return mdd;
}

/** 샤프 비율 (무위험 0, 일별 수익률 연환산 √252). 표본 부족·무변동 시 null */
export function sharpeRatio(returns: number[]): number | null {
  if (returns.length < 2) return null;
  const mean = returns.reduce((s, r) => s + r, 0) / returns.length;
  const variance = returns.reduce((s, r) => s + (r - mean) ** 2, 0) / (returns.length - 1);
  const sd = Math.sqrt(variance);
  if (sd === 0) return null;
  return (mean / sd) * Math.sqrt(252);
}
