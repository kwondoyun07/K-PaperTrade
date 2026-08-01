export type Bar = {
  ts: string; // 'YYYY-MM-DD HH:MM' KST
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type Side = "BUY" | "SELL";
export type OrderType = "MARKET" | "LIMIT";

export type OrderReq = {
  side: Side;
  type: OrderType;
  qty: number;
  limitPrice?: number; // LIMIT만
};

export type EngineConfig = {
  slippageBp: number; // 시장가 슬리피지 (basis point)
  commissionRate: number;
  sellTaxRate: number;
};

export type RejectReason =
  | "상한가"
  | "하한가"
  | "거래량0"
  | "호가단위"
  | "가격제한폭"
  | "수량오류"
  | "지정가없음";

export type Fill = {
  price: number; // 슬리피지 반영, 호가단위 절사(원)
  qty: number;
  commission: number;
  tax: number;
  ts: string; // 체결 분봉 시각
};

export type FillResult =
  | { status: "FILLED"; fill: Fill }
  | { status: "REJECTED"; reason: RejectReason }
  | { status: "PENDING" }; // 지정가 미체결 — 다음 분봉으로 재판정
