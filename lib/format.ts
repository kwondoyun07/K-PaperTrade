// 한국식 색상 컨벤션: 상승/수익 = 빨강, 하락/손실 = 파랑
export const UP = "#F04452";
export const DOWN = "#3182F6";
export const NEUTRAL = "#8B8D98";

export const won = (n: number) => "₩" + Math.round(n).toLocaleString("ko-KR");

export const sgnWon = (n: number) =>
  (n > 0 ? "+" : n < 0 ? "−" : "") +
  "₩" +
  Math.abs(Math.round(n)).toLocaleString("ko-KR");

export const pct = (n: number) =>
  (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n).toFixed(2) + "%";

export const clr = (n: number) => (n > 0 ? UP : n < 0 ? DOWN : NEUTRAL);

/** AI 근거는 "[opus=BUY sonnet=HOLD ... →SELL 3/3응답] 실제 사유" 형태다.
 *  앞의 모델별 투표와 뒤의 산문을 나눠 투표는 흐리게, 사유는 또렷하게 보여준다. */
export function splitReason(reason: string): { votes: string | null; text: string } {
  const m = /^\[([^\]]*)\]\s*(.*)$/s.exec(reason);
  return m ? { votes: m[1], text: m[2] } : { votes: null, text: reason };
}
