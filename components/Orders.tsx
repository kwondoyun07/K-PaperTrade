"use client";

// 주문·체결 내역 — 거부 사유 뱃지 포함
import { useEffect, useState } from "react";
import { DOWN, UP, won } from "@/lib/format";
import { j, type OrderRow } from "./client";

const th: React.CSSProperties = {
  color: "#8B8D98", fontWeight: 500, fontSize: 12, padding: "6px 0",
  borderBottom: "1px solid #1F1F26", textAlign: "right",
};
const td: React.CSSProperties = {
  padding: "9px 0", borderBottom: "1px solid #1A1A20", textAlign: "right", fontSize: 13,
};

function StatusBadge({ status, reason }: { status: string; reason: string | null }) {
  const style: React.CSSProperties = {
    fontSize: 11, fontWeight: 700, padding: "2px 7px", borderRadius: 6, whiteSpace: "nowrap",
  };
  if (status === "FILLED") return <span style={{ ...style, color: "#4CAF7D", background: "rgba(76,175,125,0.12)" }}>체결</span>;
  if (status === "REJECTED")
    return <span style={{ ...style, color: UP, background: "rgba(240,68,82,0.12)" }}>거부 · {reason ?? "?"}</span>;
  if (status === "CANCELLED") return <span style={{ ...style, color: "#8B8D98", background: "#1C1C22" }}>취소</span>;
  return <span style={{ ...style, color: "#E8C55A", background: "rgba(232,197,90,0.12)" }}>대기</span>;
}

export default function Orders({ accountId, active }: { accountId: number | null; active: boolean }) {
  const [orders, setOrders] = useState<OrderRow[]>([]);

  useEffect(() => {
    if (!active || !accountId) return;
    j<{ orders: OrderRow[] }>(`/api/v1/orders?account_id=${accountId}`)
      .then((r) => setOrders(r.orders))
      .catch(() => {});
  }, [active, accountId]);

  return (
    <section style={{ maxWidth: 1180 }}>
      <div className="card" style={{ padding: 18 }}>
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>주문·체결 내역</div>
        {orders.length ? (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ ...th, textAlign: "left" }}>주문시각</th>
                <th style={{ ...th, textAlign: "left" }}>종목</th>
                <th style={{ ...th, textAlign: "center" }}>구분</th>
                <th style={th}>유형</th>
                <th style={th}>수량</th>
                <th style={th}>지정가</th>
                <th style={th}>체결가</th>
                <th style={th}>수수료+세금</th>
                <th style={{ ...th, textAlign: "center" }}>상태</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td style={{ ...td, textAlign: "left", color: "#8B8D98", fontSize: 12 }}>{o.ordered_at}</td>
                  <td style={{ ...td, textAlign: "left", fontWeight: 600 }}>{o.ticker}</td>
                  <td style={{ ...td, textAlign: "center", color: o.side === "BUY" ? UP : DOWN, fontWeight: 700 }}>
                    {o.side === "BUY" ? "매수" : "매도"}
                  </td>
                  <td style={{ ...td, color: "#B7B9C2" }}>{o.order_type === "MARKET" ? "시장가" : "지정가"}</td>
                  <td style={td}>{o.qty.toLocaleString("ko-KR")}</td>
                  <td style={{ ...td, color: "#B7B9C2" }}>{o.limit_price ? won(o.limit_price) : "—"}</td>
                  <td style={td}>{o.exec_price ? won(o.exec_price) : "—"}</td>
                  <td style={{ ...td, color: "#B7B9C2" }}>
                    {o.commission != null ? won((o.commission ?? 0) + (o.tax ?? 0)) : "—"}
                  </td>
                  <td style={{ ...td, textAlign: "center" }}>
                    <StatusBadge status={o.status} reason={o.reject_reason} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ padding: "40px 0", textAlign: "center", fontSize: 13, color: "#8B8D98" }}>
            주문 내역이 없습니다 — 종목 상세에서 주문을 넣어보세요
          </div>
        )}
      </div>
    </section>
  );
}
