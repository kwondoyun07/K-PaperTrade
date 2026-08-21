"use client";

// AI 판단 로그 — 판단 vs 이후 수익률 (ret_d5/d20/d60은 6단계 배치가 채움)
import { useEffect, useState } from "react";
import { clr, DOWN, NEUTRAL, pct, UP } from "@/lib/format";
import { fetchStockNames, j } from "./client";

type Decision = {
  id: number; ticker: string; ts: string; action: "BUY" | "SELL" | "HOLD";
  reason_summary: string | null; source: string | null;
  ret_d5: number | null; ret_d20: number | null; ret_d60: number | null;
  // 'decision' = 판단 시점가 기준(신뢰 가능). 그 외(NULL·'close')는 판단일 종가 기준이라
  // 같은 날·같은 종목의 BUY와 HOLD가 같은 값을 받는 옛 계산이다 — 화면에서 구분해 표시한다.
  ret_basis: string | null;
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
                    <td style={td}>{ret(d.ret_d5, d.ret_basis === "decision")}</td>
                    <td style={td}>{ret(d.ret_d20, d.ret_basis === "decision")}</td>
                    <td style={td}>{ret(d.ret_d60, d.ret_basis === "decision")}</td>
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
