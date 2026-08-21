"use client";

// 주문 패널 — 종목 상세에서 사용. 제출은 부모가 처리.
import { useState } from "react";
import { DOWN, UP, won } from "@/lib/format";
import { estimateCost } from "@/lib/engine/fill";
import { seg } from "@/lib/ui";

export type OrderReqUi = {
  side: "BUY" | "SELL";
  type: "MARKET" | "LIMIT";
  qty: number;
  limitPrice?: number;
};

export default function OrderPanel({
  stockName,
  refPrice,
  position,
  note,
  disabled,
  onSubmit,
}: {
  stockName: string;
  refPrice: number | null;
  position: { qty: number; avgPrice: number } | null;
  note?: string;
  disabled?: boolean;
  onSubmit: (req: OrderReqUi) => Promise<void> | void;
}) {
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [oType, setOType] = useState<"MARKET" | "LIMIT">("MARKET");
  const [qty, setQty] = useState("");
  const [limitPx, setLimitPx] = useState("");

  const q = Math.max(0, parseInt(qty) || 0);
  const px = oType === "LIMIT" ? parseInt(limitPx) || refPrice || 0 : refPrice || 0;
  const est = estimateCost(side, px, q);
  const rowStyle: React.CSSProperties = { display: "flex", justifyContent: "space-between" };

  return (
    <div className="card" style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 4, background: "#111114", borderRadius: 9, padding: 3 }}>
        <button onClick={() => setSide("BUY")} style={{ ...seg(side === "BUY", UP), flex: 1, height: 34, fontSize: 13 }}>
          매수
        </button>
        <button onClick={() => setSide("SELL")} style={{ ...seg(side === "SELL", DOWN), flex: 1, height: 34, fontSize: 13 }}>
          매도
        </button>
      </div>
      <div style={{ display: "flex", gap: 4 }}>
        <button
          onClick={() => setOType("MARKET")}
          style={{ ...seg(oType === "MARKET"), flex: 1, border: "1px solid " + (oType === "MARKET" ? "#3C3C46" : "#26262E"), background: oType === "MARKET" ? "#26262E" : "#111114" }}
        >
          시장가
        </button>
        <button
          onClick={() => {
            setOType("LIMIT");
            setLimitPx((p) => p || (refPrice ? String(refPrice) : ""));
          }}
          style={{ ...seg(oType === "LIMIT"), flex: 1, border: "1px solid " + (oType === "LIMIT" ? "#3C3C46" : "#26262E"), background: oType === "LIMIT" ? "#26262E" : "#111114" }}
        >
          지정가
        </button>
      </div>
      {oType === "LIMIT" && (
        <label style={{ display: "flex", flexDirection: "column", gap: 5, fontSize: 12, color: "#8B8D98" }}>
          지정가 (₩)
          <input type="number" className="input" value={limitPx} onChange={(e) => setLimitPx(e.target.value)} />
        </label>
      )}
      <label style={{ display: "flex", flexDirection: "column", gap: 5, fontSize: 12, color: "#8B8D98" }}>
        수량 (주)
        <input type="number" className="input" placeholder="0" value={qty} onChange={(e) => setQty(e.target.value)} />
      </label>
      <div style={{ display: "flex", flexDirection: "column", gap: 7, background: "#111114", borderRadius: 10, padding: 12, fontSize: 12 }}>
        <div style={rowStyle}>
          <span style={{ color: "#8B8D98" }}>{oType === "MARKET" ? "예상 체결단가" : "지정가"}</span>
          <span>{px ? won(px) : "—"}</span>
        </div>
        <div style={rowStyle}>
          <span style={{ color: "#8B8D98" }}>주문금액</span>
          <span>{won(est.amount)}</span>
        </div>
        <div style={rowStyle}>
          <span style={{ color: "#8B8D98" }}>수수료 (0.015%)</span>
          <span>{won(est.commission)}</span>
        </div>
        <div style={rowStyle}>
          <span style={{ color: "#8B8D98" }}>거래세 (0.15%)</span>
          <span>{side === "SELL" ? won(est.tax) : "—"}</span>
        </div>
        <div style={{ height: 1, background: "#26262E", margin: "2px 0" }} />
        <div style={{ ...rowStyle, fontSize: 13, fontWeight: 700 }}>
          <span>{side === "BUY" ? "총 매수금액" : "총 매도금액(세후)"}</span>
          <span style={{ color: side === "BUY" ? UP : DOWN }}>{won(est.total)}</span>
        </div>
      </div>
      <div style={{ fontSize: 12, color: "#8B8D98", display: "flex", justifyContent: "space-between" }}>
        <span>보유</span>
        <span>
          {position && position.qty > 0
            ? `${position.qty.toLocaleString("ko-KR")}주 · 평단 ${won(position.avgPrice)}`
            : "없음"}
        </span>
      </div>
      {note && <div style={{ fontSize: 11, color: "#5C5E68" }}>{note}</div>}
      <button
        disabled={disabled}
        onClick={() =>
          onSubmit({ side, type: oType, qty: q, limitPrice: oType === "LIMIT" ? parseInt(limitPx) || undefined : undefined })
        }
        style={{
          height: 42, borderRadius: 10, border: "none", cursor: disabled ? "not-allowed" : "pointer",
          fontSize: 14, fontWeight: 700, color: "#fff",
          background: side === "BUY" ? UP : DOWN, opacity: disabled ? 0.5 : 1,
        }}
      >
        {stockName} {side === "BUY" ? "매수" : "매도"}
      </button>
    </div>
  );
}
