"use client";

import { useEffect, useRef, useState } from "react";
import { curve, FILLS, HOLDINGS, seedOf, series, START_CASH, STOCKS } from "@/lib/sim";
import { clr, DOWN, NEUTRAL, pct, sgnWon, UP, won } from "@/lib/format";
import { seg, setupCanvas } from "@/lib/ui";

type Period = "1M" | "3M" | "1Y";

function drawDash(cv: HTMLCanvasElement, period: Period, account: string) {
  const c = setupCanvas(cv);
  if (!c) return;
  const { g, W, H } = c;
  const n = { "1M": 22, "3M": 66, "1Y": 252 }[period];
  const seed = seedOf("dash" + period + account);
  const empty = account === "fresh";
  const lines = [
    { d: curve(seed + 1, n, empty ? 0 : 0.11, empty ? 0.02 : 0.9), col: UP, w: 2 },
    { d: curve(seed + 2, n, 0.05, 0.6), col: NEUTRAL, w: 1.5 },
    { d: curve(seed + 3, n, 0.03, 0.9), col: DOWN, w: 1.5 },
  ];
  const all = lines.flatMap((l) => l.d);
  const mn = Math.min(...all);
  const mx = Math.max(...all);
  const pad = (mx - mn) * 0.1 || 1;
  const y = (v: number) => 8 + (H - 30) * (1 - (v - mn + pad) / (mx - mn + 2 * pad));
  const x = (i: number) => 4 + ((W - 52) * i) / (n - 1);
  g.strokeStyle = "#1F1F26";
  g.fillStyle = "#5C5E68";
  g.textAlign = "left";
  for (let k = 0; k <= 3; k++) {
    const v = mn - pad + ((mx - mn + 2 * pad) * k) / 3;
    const yy = y(v);
    g.beginPath();
    g.moveTo(0, yy);
    g.lineTo(W - 48, yy);
    g.stroke();
    g.fillText(pct(v).replace("−", "-"), W - 44, yy + 4);
  }
  for (const L of lines) {
    g.strokeStyle = L.col;
    g.lineWidth = L.w;
    g.beginPath();
    L.d.forEach((v, i) => (i ? g.lineTo(x(i), y(v)) : g.moveTo(x(i), y(v))));
    g.stroke();
  }
  g.fillStyle = "#5C5E68";
  g.textAlign = "center";
  const labels: Record<Period, string[]> = {
    "1M": ["7/1", "7/10", "7/20", "7/31"],
    "3M": ["5월", "6월", "7월", "8월"],
    "1Y": ["25.9", "25.12", "26.3", "26.7"],
  };
  labels[period].forEach((t, i) => g.fillText(t, x(Math.round(((n - 1) * i) / 3)), H - 4));
  g.lineWidth = 1;
}

const th: React.CSSProperties = {
  color: "#8B8D98",
  fontWeight: 500,
  fontSize: 12,
  padding: "6px 0",
  borderBottom: "1px solid #1F1F26",
  textAlign: "right",
};
const td: React.CSSProperties = {
  padding: "10px 0",
  borderBottom: "1px solid #1A1A20",
  textAlign: "right",
};

export default function Dashboard({ account, active }: { account: string; active: boolean }) {
  const [period, setPeriod] = useState<Period>("1M");
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!active) return;
    const draw = () => ref.current && drawDash(ref.current, period, account);
    draw();
    window.addEventListener("resize", draw);
    return () => window.removeEventListener("resize", draw);
  }, [period, account, active]);

  const empty = account === "fresh";
  const lastClose = (code: string) => series(code, "2026-07-31")[390].c;

  let evalSum = 0;
  let plSum = 0;
  const holdRows = empty
    ? []
    : HOLDINGS.map((h) => {
        const st = STOCKS.find((x) => x.code === h.code)!;
        const cur = lastClose(h.code);
        const pl = (cur - h.avg) * h.qty;
        const rate = (cur / h.avg - 1) * 100;
        evalSum += cur * h.qty;
        plSum += pl;
        return {
          name: st.name,
          qty: h.qty.toLocaleString("ko-KR"),
          avg: won(h.avg),
          cur: won(cur),
          pl: sgnWon(pl),
          rate: pct(rate),
          color: clr(pl),
        };
      });

  const cash = empty ? START_CASH : 12_450_000;
  const total = cash + evalSum;
  const dayRate = empty ? 0 : 0.84;
  const metricCards = [
    {
      label: "총자산",
      value: won(total),
      sub: empty ? "초기 자본" : "전일 대비 " + sgnWon((total * dayRate) / 100),
      color: "#E8E8EC",
      subColor: empty ? "#5C5E68" : clr(dayRate),
    },
    {
      label: "평가손익",
      value: sgnWon(plSum),
      sub: empty ? "보유종목 없음" : pct((plSum / (evalSum - plSum)) * 100),
      color: clr(plSum),
      subColor: clr(plSum),
    },
    { label: "현금", value: won(cash), sub: "주문 가능 금액", color: "#E8E8EC", subColor: "#5C5E68" },
    {
      label: "일간수익률",
      value: pct(dayRate),
      sub: "KOSPI " + pct(0.31),
      color: clr(dayRate),
      subColor: "#5C5E68",
    },
  ];

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 1180 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }}>
        {metricCards.map((m) => (
          <div key={m.label} className="card" style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={{ fontSize: 12, color: "#8B8D98" }}>{m.label}</span>
            <span style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.4px", color: m.color }}>{m.value}</span>
            <span style={{ fontSize: 12, color: m.subColor }}>{m.sub}</span>
          </div>
        ))}
      </div>

      <div className="card" style={{ padding: 18 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <span style={{ fontSize: 15, fontWeight: 700 }}>수익률 추이</span>
            <div style={{ display: "flex", gap: 12, fontSize: 12, color: "#8B8D98" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <span style={{ width: 10, height: 2, background: UP }} />내 포트폴리오
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <span style={{ width: 10, height: 2, background: NEUTRAL }} />KOSPI
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <span style={{ width: 10, height: 2, background: DOWN }} />KOSDAQ
              </span>
            </div>
          </div>
          <div style={{ display: "flex", gap: 4, background: "#111114", borderRadius: 9, padding: 3 }}>
            {(["1M", "3M", "1Y"] as Period[]).map((p) => (
              <button key={p} onClick={() => setPeriod(p)} style={seg(period === p)}>
                {p}
              </button>
            ))}
          </div>
        </div>
        <canvas ref={ref} style={{ width: "100%", height: 250, display: "block" }} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 16, alignItems: "start" }}>
        <div className="card" style={{ padding: 18 }}>
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>보유종목</div>
          {holdRows.length > 0 ? (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr>
                  <th style={{ ...th, textAlign: "left" }}>종목명</th>
                  <th style={th}>수량</th>
                  <th style={th}>평단가</th>
                  <th style={th}>현재가</th>
                  <th style={th}>평가손익</th>
                  <th style={th}>수익률</th>
                </tr>
              </thead>
              <tbody>
                {holdRows.map((h) => (
                  <tr key={h.name}>
                    <td style={{ ...td, textAlign: "left", fontWeight: 600 }}>{h.name}</td>
                    <td style={{ ...td, color: "#B7B9C2" }}>{h.qty}</td>
                    <td style={{ ...td, color: "#B7B9C2" }}>{h.avg}</td>
                    <td style={td}>{h.cur}</td>
                    <td style={{ ...td, color: h.color }}>{h.pl}</td>
                    <td style={{ ...td, color: h.color, fontWeight: 600 }}>{h.rate}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div style={{ padding: "40px 0", textAlign: "center", display: "flex", flexDirection: "column", gap: 8, alignItems: "center" }}>
              <div style={{ width: 40, height: 40, borderRadius: 12, background: "#1C1C22", border: "1px dashed #2C2C36", display: "flex", alignItems: "center", justifyContent: "center", color: "#5C5E68", fontSize: 18 }}>
                —
              </div>
              <span style={{ fontSize: 13, color: "#8B8D98" }}>보유종목이 없습니다</span>
              <span style={{ fontSize: 12, color: "#5C5E68" }}>리플레이 모드에서 매매 연습을 시작해보세요</span>
            </div>
          )}
        </div>

        <div className="card" style={{ padding: 18 }}>
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>최근 체결</div>
          {!empty ? (
            <div style={{ display: "flex", flexDirection: "column" }}>
              {FILLS.map((f, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 0", borderBottom: "1px solid #1A1A20", fontSize: 13 }}>
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      padding: "2px 7px",
                      borderRadius: 6,
                      color: f.side === "매수" ? UP : DOWN,
                      background: f.side === "매수" ? "rgba(240,68,82,0.12)" : "rgba(49,130,246,0.12)",
                    }}
                  >
                    {f.side}
                  </span>
                  <span style={{ fontWeight: 600, flex: 1 }}>{f.name}</span>
                  <span style={{ color: "#B7B9C2" }}>{f.detail}</span>
                  <span style={{ color: "#5C5E68", fontSize: 12 }}>{f.time}</span>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ padding: "40px 0", textAlign: "center", fontSize: 13, color: "#8B8D98" }}>체결 내역이 없습니다</div>
          )}
        </div>
      </div>
    </section>
  );
}
