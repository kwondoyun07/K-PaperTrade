"use client";

// 대시보드 — 실데이터 (portfolio·orders·performance API)
import { useCallback, useEffect, useRef, useState } from "react";
import { clr, DOWN, NEUTRAL, pct, sgnWon, UP, won } from "@/lib/format";
import { setupCanvas } from "@/lib/ui";
import { j, type OrderRow, type Portfolio } from "./client";

type Account = { id: number; name: string; initial_cash: number };
type Snapshot = { ts: string; equity: number };
type IndexRow = { code: string; date: string; close: number };
type Metrics = { returnPct: number; mddPct: number; sharpe: number | null } | null;

function drawCurve(cv: HTMLCanvasElement, snaps: Snapshot[], indices: IndexRow[], initial: number) {
  const c = setupCanvas(cv);
  if (!c) return;
  const { g, W, H } = c;
  g.clearRect(0, 0, W, H);

  // 수익률(%) 곡선으로 정규화
  const port = snaps.map((s) => (s.equity / initial - 1) * 100);
  const mkIdx = (code: string) => {
    const rows = indices.filter((r) => r.code === code);
    if (rows.length < 2) return [];
    const base = rows[0].close;
    return rows.map((r) => (r.close / base - 1) * 100);
  };
  const lines = [
    { d: port, col: UP, w: 2 },
    { d: mkIdx("KOSPI"), col: NEUTRAL, w: 1.5 },
    { d: mkIdx("KOSDAQ"), col: DOWN, w: 1.5 },
  ].filter((l) => l.d.length >= 2);
  if (!lines.length) return;

  const all = lines.flatMap((l) => l.d);
  const mn = Math.min(...all);
  const mx = Math.max(...all);
  const pad = (mx - mn) * 0.1 || 1;
  const y = (v: number) => 8 + (H - 30) * (1 - (v - mn + pad) / (mx - mn + 2 * pad));
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
    const x = (i: number) => 4 + ((W - 52) * i) / Math.max(1, L.d.length - 1);
    g.strokeStyle = L.col;
    g.lineWidth = L.w;
    g.beginPath();
    L.d.forEach((v, i) => (i ? g.lineTo(x(i), y(v)) : g.moveTo(x(i), y(v))));
    g.stroke();
  }
  g.lineWidth = 1;
}

const th: React.CSSProperties = {
  color: "#8B8D98", fontWeight: 500, fontSize: 12, padding: "6px 0",
  borderBottom: "1px solid #1F1F26", textAlign: "right",
};
const td: React.CSSProperties = {
  padding: "10px 0", borderBottom: "1px solid #1A1A20", textAlign: "right",
};

export default function Dashboard({
  account,
  active,
  onOpenStock,
}: {
  account: Account | null;
  active: boolean;
  onOpenStock: (ticker: string) => void;
}) {
  const [pf, setPf] = useState<Portfolio | null>(null);
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [perf, setPerf] = useState<{ snapshots: Snapshot[]; indices: IndexRow[]; metrics?: Metrics }>({ snapshots: [], indices: [] });
  const [names, setNames] = useState<Record<string, string>>({});
  const ref = useRef<HTMLCanvasElement>(null);

  const load = useCallback(async () => {
    if (!account) return;
    const [p, o, pe] = await Promise.all([
      j<Portfolio>(`/api/v1/accounts/${account.id}/portfolio`),
      j<{ orders: OrderRow[] }>(`/api/v1/orders?account_id=${account.id}`),
      j<{ snapshots: Snapshot[]; indices: IndexRow[]; metrics?: Metrics }>(`/api/v1/accounts/${account.id}/performance`),
    ]);
    setPf(p);
    setOrders(o.orders);
    setPerf(pe);
    const tickers = [...new Set(p.positions.map((x) => x.ticker))];
    const nm: Record<string, string> = {};
    await Promise.all(
      tickers.map(async (t) => {
        const r = await j<{ results: { ticker: string; name: string }[] }>(`/api/v1/stocks/search?q=${t}`);
        if (r.results[0]) nm[t] = r.results[0].name;
      }),
    );
    setNames(nm);
  }, [account]);

  useEffect(() => {
    if (active) load().catch(() => {});
  }, [active, load]);

  useEffect(() => {
    if (!active || !account) return;
    const draw = () => ref.current && drawCurve(ref.current, perf.snapshots, perf.indices, account.initial_cash);
    draw();
    window.addEventListener("resize", draw);
    return () => window.removeEventListener("resize", draw);
  }, [active, perf, account]);

  if (!account) return null;
  const plSum = pf?.positions.reduce((s, p) => s + p.pnl, 0) ?? 0;
  const costSum = pf?.positions.reduce((s, p) => s + p.avgPrice * p.qty, 0) ?? 0;
  const equity = pf?.equity ?? account.initial_cash;
  const totalRet = (equity / account.initial_cash - 1) * 100;
  const fills = orders.filter((o) => o.status === "FILLED").slice(0, 5);
  const hasCurve = perf.snapshots.length >= 2;

  const metricCards = [
    { label: "총자산", value: won(equity), sub: `초기 자본 ${won(account.initial_cash)}`, color: "#E8E8EC", subColor: "#5C5E68" },
    { label: "평가손익", value: sgnWon(plSum), sub: costSum > 0 ? pct((plSum / costSum) * 100) : "보유종목 없음", color: clr(plSum), subColor: clr(plSum) },
    { label: "현금", value: won(pf?.cash ?? account.initial_cash), sub: "주문 가능 금액", color: "#E8E8EC", subColor: "#5C5E68" },
    { label: "누적수익률", value: pct(totalRet), sub: "초기 자본 대비", color: clr(totalRet), subColor: "#5C5E68" },
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
          {perf.metrics && (
            <div style={{ display: "flex", gap: 14, fontSize: 12, color: "#8B8D98" }}>
              <span>
                MDD <span style={{ color: "#E8E8EC", fontWeight: 600 }}>{perf.metrics.mddPct.toFixed(2)}%</span>
              </span>
              <span>
                샤프{" "}
                <span style={{ color: "#E8E8EC", fontWeight: 600 }}>
                  {perf.metrics.sharpe == null ? "—" : perf.metrics.sharpe.toFixed(2)}
                </span>
              </span>
              <span>
                누적 <span style={{ color: clr(perf.metrics.returnPct), fontWeight: 600 }}>{pct(perf.metrics.returnPct)}</span>
              </span>
            </div>
          )}
        </div>
        {hasCurve ? (
          <canvas ref={ref} style={{ width: "100%", height: 250, display: "block" }} />
        ) : (
          <div style={{ height: 250, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, color: "#5C5E68" }}>
            일일 스냅샷이 2개 이상 쌓이면 수익률 곡선이 표시됩니다 (장 마감 배치에서 기록)
          </div>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 16, alignItems: "start" }}>
        <div className="card" style={{ padding: 18 }}>
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>보유종목</div>
          {pf && pf.positions.length > 0 ? (
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
                {pf.positions.map((h) => (
                  <tr key={h.ticker} className="rowHover" style={{ cursor: "pointer" }} onClick={() => onOpenStock(h.ticker)}>
                    <td style={{ ...td, textAlign: "left", fontWeight: 600 }}>{names[h.ticker] ?? h.ticker}</td>
                    <td style={{ ...td, color: "#B7B9C2" }}>{h.qty.toLocaleString("ko-KR")}</td>
                    <td style={{ ...td, color: "#B7B9C2" }}>{won(h.avgPrice)}</td>
                    <td style={td}>{won(h.currentPrice)}</td>
                    <td style={{ ...td, color: clr(h.pnl) }}>{sgnWon(h.pnl)}</td>
                    <td style={{ ...td, color: clr(h.pnl), fontWeight: 600 }}>{pct(h.returnPct)}</td>
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
          {fills.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column" }}>
              {fills.map((f) => (
                <div key={f.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 0", borderBottom: "1px solid #1A1A20", fontSize: 13 }}>
                  <span
                    style={{
                      fontSize: 11, fontWeight: 700, padding: "2px 7px", borderRadius: 6,
                      color: f.side === "BUY" ? UP : DOWN,
                      background: f.side === "BUY" ? "rgba(240,68,82,0.12)" : "rgba(49,130,246,0.12)",
                    }}
                  >
                    {f.side === "BUY" ? "매수" : "매도"}
                  </span>
                  <span style={{ fontWeight: 600, flex: 1 }}>{names[f.ticker] ?? f.ticker}</span>
                  <span style={{ color: "#B7B9C2" }}>
                    {f.exec_qty}주 · {won(f.exec_price ?? 0)}
                  </span>
                  <span style={{ color: "#5C5E68", fontSize: 12 }}>{f.executed_at?.slice(5)}</span>
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
