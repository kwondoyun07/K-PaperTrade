"use client";

// AI 판단 로그 — 판단 vs 이후 수익률 (ret_d5/d20/d60은 6단계 배치가 채움)
import { useEffect, useState } from "react";
import { clr, DOWN, NEUTRAL, pct, UP } from "@/lib/format";
import { fetchStockNames, j } from "./client";

type Decision = {
  id: number; ticker: string; ts: string; action: "BUY" | "SELL" | "HOLD";
  reason_summary: string | null; source: string | null;
  ret_d5: number | null; ret_d20: number | null; ret_d60: number | null;
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

const ret = (v: number | null) =>
  v == null ? <span style={{ color: "#5C5E68" }}>—</span> : <span style={{ color: clr(v) }}>{pct(v)}</span>;

export default function AiLog({ active }: { active: boolean }) {
  const [rows, setRows] = useState<Decision[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!active) return;
    j<{ decisions: Decision[] }>("/api/v1/ai-decisions?limit=100")
      .then((r) => setRows(r.decisions))
      .catch(() => {});
    fetchStockNames().then(setNames);
  }, [active]);

  return (
    <section style={{ maxWidth: 1180 }}>
      <div className="card" style={{ padding: 18 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 12 }}>
          <span style={{ fontSize: 15, fontWeight: 700 }}>AI 판단 로그</span>
          <span style={{ fontSize: 12, color: "#5C5E68" }}>판단 이후 수익률(d5/d20/d60)은 장 마감 배치가 채웁니다</span>
        </div>
        {rows.length ? (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ ...th, textAlign: "left" }}>시각</th>
                <th style={{ ...th, textAlign: "left" }}>종목</th>
                <th style={{ ...th, textAlign: "center" }}>판단</th>
                <th style={{ ...th, textAlign: "left" }}>근거 요약</th>
                <th style={th}>+5일</th>
                <th style={th}>+20일</th>
                <th style={th}>+60일</th>
                <th style={{ ...th, textAlign: "left" }}>출처</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => {
                const a = ACTION_STYLE[d.action];
                return (
                  <tr key={d.id}>
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
                    <td style={td}>{ret(d.ret_d5)}</td>
                    <td style={td}>{ret(d.ret_d20)}</td>
                    <td style={td}>{ret(d.ret_d60)}</td>
                    <td style={{ ...td, textAlign: "left", color: "#5C5E68", fontSize: 12 }}>{d.source ?? "—"}</td>
                  </tr>
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
