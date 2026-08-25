"use client";

// AI 판단 로그 — 판단 vs 이후 수익률 (ret_d5/d20/d60은 6단계 배치가 채움)
import React, { useEffect, useState } from "react";
import { clr, DOWN, NEUTRAL, pct, sgnWon, splitReason, UP, won } from "@/lib/format";
import { fetchStockNames, j, type OrderRow } from "./client";

type Decision = {
  id: number; ticker: string; ts: string; action: "BUY" | "SELL" | "HOLD";
  reason_summary: string | null; source: string | null;
  ret_d5: number | null; ret_d20: number | null; ret_d60: number | null;
  // 'decision' = 판단 시점가 기준(신뢰 가능). 그 외(NULL·'close')는 판단일 종가 기준이라
  // 같은 날·같은 종목의 BUY와 HOLD가 같은 값을 받는 옛 계산이다 — 화면에서 구분해 표시한다.
  ret_basis: string | null;
  decision_price: number | null; // 판단 시점에 AI가 실제로 본 가격 — 수익률의 기준가
  order_id: number | null;       // 이 판단이 낸 주문 (HOLD·스킵이면 null)
};

const th: React.CSSProperties = {
  color: "#8B8D98", fontWeight: 500, fontSize: 12, padding: "6px 0",
  borderBottom: "1px solid #1F1F26", textAlign: "right",
};
const td: React.CSSProperties = {
  padding: "9px 0", borderBottom: "1px solid #1A1A20", textAlign: "right", fontSize: 13,
};

const ACTION_STYLE = {
  BUY: { color: UP, background: "rgba(240,68,82,0.12)", label: "매수" },
  SELL: { color: DOWN, background: "rgba(49,130,246,0.12)", label: "매도" },
  HOLD: { color: NEUTRAL, background: "#1C1C22", label: "관망" },
} as const;

const ret = (v: number | null, trusted = true) => {
  if (v == null) return <span style={{ color: "#5C5E68" }}>—</span>;
  // 옛 기준(판단일 종가)으로 계산된 값은 흐리게 + 별표. 색까지 그대로 주면 신뢰할 수
  // 있는 숫자로 오독된다 — 실제로 그 값들로 잘못된 결론을 낸 적이 있다.
  if (!trusted)
    return (
      <span style={{ color: "#5C5E68" }} title="판단일 종가 기준(옛 계산) — 신뢰할 수 없음">
        {pct(v)}*
      </span>
    );
  return <span style={{ color: clr(v) }}>{pct(v)}</span>;
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ minWidth: 128 }}>
      <div style={{ fontSize: 11, color: "#5C5E68", marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 13, color: "#E8E8EC" }}>{children}</div>
    </div>
  );
}

/** 펼친 판단의 상세 — 표에서 잘리는 근거 전문과, 그 판단이 실제로 무엇이 됐는지. */
function Detail({ d, order }: { d: Decision; order: OrderRow | null }) {
  const { votes, text } = splitReason(d.reason_summary ?? "");
  const trusted = d.ret_basis === "decision";
  // ret_basis는 수익률을 채우는 배치가 함께 적는다. 아직 5거래일이 안 지난 판단은
  // NULL인데, 이걸 '옛 계산'으로 단정하면 오늘 판단이 못 믿을 값처럼 보인다.
  const scored = d.ret_d5 != null || d.ret_d20 != null || d.ret_d60 != null;
  return (
    <div style={{ padding: "14px 16px 16px", background: "#141419", borderRadius: 10, margin: "0 0 10px" }}>
      {votes ? (
        <div style={{ fontSize: 12, color: "#8B8D98", marginBottom: 8, fontFamily: "ui-monospace, monospace" }}>{votes}</div>
      ) : null}
      <div style={{ fontSize: 13.5, color: "#E8E8EC", lineHeight: 1.65, marginBottom: 14 }}>{text || "근거 없음"}</div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "14px 28px" }}>
        <Field label="판단 시점가">
          {d.decision_price ? won(d.decision_price) : <span style={{ color: "#5C5E68" }}>기록 없음</span>}
        </Field>
        <Field label="수익률 기준">
          {trusted ? (
            "판단 시점가"
          ) : scored ? (
            <span style={{ color: "#8B8D98" }} title="같은 날·같은 종목의 BUY와 HOLD가 같은 값을 받는 옛 계산">
              판단일 종가(옛 계산)
            </span>
          ) : (
            <span style={{ color: "#5C5E68" }} title="판단 후 5거래일이 지나야 채워집니다">
              아직 채점 전
            </span>
          )}
        </Field>
        <Field label="+5일">{ret(d.ret_d5, trusted)}</Field>
        <Field label="+20일">{ret(d.ret_d20, trusted)}</Field>
        <Field label="+60일">{ret(d.ret_d60, trusted)}</Field>
        <Field label="출처">{d.source ?? "—"}</Field>
      </div>

      <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid #1F1F26" }}>
        {order ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "14px 28px", alignItems: "flex-start" }}>
            <Field label="주문">
              #{order.id} · {order.order_type === "MARKET" ? "시장가" : "지정가"} {order.qty.toLocaleString("ko-KR")}주
            </Field>
            <Field label="체결가">{order.exec_price ? won(order.exec_price) : "—"}</Field>
            <Field label="수수료+세금">
              {order.commission != null ? won((order.commission ?? 0) + (order.tax ?? 0)) : "—"}
            </Field>
            <Field label="실현손익">
              {order.realized == null ? (
                <span style={{ color: "#5C5E68" }}>매수는 없음</span>
              ) : (
                <span style={{ color: clr(order.realized), fontWeight: 600 }}>{sgnWon(order.realized)}</span>
              )}
            </Field>
            <Field label="상태">
              {order.status === "FILLED" ? "체결" : order.status === "REJECTED" ? `거부 · ${order.reject_reason ?? "?"}` : order.status}
            </Field>
          </div>
        ) : (
          <div style={{ fontSize: 12.5, color: "#8B8D98" }}>
            {d.action === "HOLD"
              ? "관망 판단이라 주문이 나가지 않았습니다."
              : "판단은 났지만 주문이 나가지 않았습니다 — 현금·비중 한도나 일일 주문 상한에 걸린 경우입니다."}
          </div>
        )}
      </div>
    </div>
  );
}

export default function AiLog({ accountId, active }: { accountId: number | null; active: boolean }) {
  const [rows, setRows] = useState<Decision[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [orders, setOrders] = useState<Record<number, OrderRow>>({});
  const [open, setOpen] = useState<number | null>(null);

  useEffect(() => {
    if (!active) return;
    j<{ decisions: Decision[] }>("/api/v1/ai-decisions?limit=100")
      .then((r) => setRows(r.decisions))
      .catch(() => {});
    fetchStockNames().then(setNames);
  }, [active]);

  useEffect(() => {
    if (!active || !accountId) return;
    // 체결가·제비용·실현손익은 주문 API가 이미 계산한다 — 여기서 다시 만들지 않는다.
    j<{ orders: OrderRow[] }>(`/api/v1/orders?account_id=${accountId}`)
      .then((r) => setOrders(Object.fromEntries(r.orders.map((o) => [o.id, o]))))
      .catch(() => {});
  }, [active, accountId]);

  return (
    <section style={{ maxWidth: 1180 }}>
      <div className="card" style={{ padding: 18 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 12 }}>
          <span style={{ fontSize: 15, fontWeight: 700 }}>AI 판단 로그</span>
          <span style={{ fontSize: 12, color: "#5C5E68" }}>
            판단이 맞았는지 채점 — 그 종목이 <b>판단 시점 대비</b> 며칠 뒤 얼마나 올랐나.
            BUY는 높을수록, SELL은 낮을수록 맞은 것. 해당 거래일이 지나야 채워집니다(+20일·+60일은 아직 축적 중).
          </span>
        </div>
        {rows.length ? (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ ...th, textAlign: "left" }}>시각</th>
                <th style={{ ...th, textAlign: "left" }}>종목</th>
                <th style={{ ...th, textAlign: "center" }}>판단</th>
                <th style={{ ...th, textAlign: "left" }}>근거 요약</th>
                <th style={th} title="판단 후 5거래일 뒤 수익률">5일 후</th>
                <th style={th} title="판단 후 20거래일 뒤 수익률">20일 후</th>
                <th style={th} title="판단 후 60거래일 뒤 수익률">60일 후</th>
                <th style={{ ...th, textAlign: "left" }}>출처</th>
                <th style={{ ...th, width: 20 }} aria-label="상세" />
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => {
                const a = ACTION_STYLE[d.action];
                const isOpen = open === d.id;
                return (
                  <React.Fragment key={d.id}>
                  <tr
                    onClick={() => setOpen(isOpen ? null : d.id)}
                    style={{ cursor: "pointer", background: isOpen ? "#16161C" : undefined }}
                    title="눌러서 상세 보기"
                  >
                    <td style={{ ...td, textAlign: "left", color: "#8B8D98", fontSize: 12 }}>{d.ts}</td>
                    <td style={{ ...td, textAlign: "left", fontWeight: 600 }}>
                      {names[d.ticker] ?? d.ticker}
                      <span style={{ color: "#5C5E68", fontSize: 11, fontWeight: 400, marginLeft: 6 }}>{d.ticker}</span>
                    </td>
                    <td style={{ ...td, textAlign: "center" }}>
                      <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 7px", borderRadius: 6, color: a.color, background: a.background }}>
                        {a.label}
                      </span>
                    </td>
                    <td style={{ ...td, textAlign: "left", color: "#B7B9C2", fontSize: 12, maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {d.reason_summary ?? "—"}
                    </td>
                    <td style={td}>{ret(d.ret_d5, d.ret_basis === "decision")}</td>
                    <td style={td}>{ret(d.ret_d20, d.ret_basis === "decision")}</td>
                    <td style={td}>{ret(d.ret_d60, d.ret_basis === "decision")}</td>
                    <td style={{ ...td, textAlign: "left", color: "#5C5E68", fontSize: 12 }}>{d.source ?? "—"}</td>
                    <td style={{ ...td, color: "#5C5E68", fontSize: 11 }}>{isOpen ? "▲" : "▼"}</td>
                  </tr>
                  {isOpen ? (
                    <tr>
                      <td colSpan={9} style={{ padding: 0 }}>
                        <Detail d={d} order={d.order_id ? (orders[d.order_id] ?? null) : null} />
                      </td>
                    </tr>
                  ) : null}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div style={{ padding: "40px 0", textAlign: "center", fontSize: 13, color: "#8B8D98" }}>
            기록된 판단이 없습니다 — POST /api/v1/ai-decisions로 기록합니다
          </div>
        )}
      </div>
    </section>
  );
}
