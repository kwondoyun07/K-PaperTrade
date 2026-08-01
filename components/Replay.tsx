"use client";

import { useEffect, useRef, useState } from "react";
import { Bar, FEE_RATE, SELL_TAX_RATE, series, STOCKS } from "@/lib/sim";
import { clr, DOWN, NEUTRAL, pct, sgnWon, UP, won } from "@/lib/format";
import { seg, setupCanvas } from "@/lib/ui";

type Trade = { i: number; side: "buy" | "sell"; px: number; qty: number };

const SPEED_MS: Record<number, number> = { 1: 900, 10: 90, 60: 15 };

function drawReplay(cv: HTMLCanvasElement, s: Bar[], idx: number, trades: Trade[]) {
  const c = setupCanvas(cv);
  if (!c) return;
  const { g, W, H } = c;
  const end = idx + 1;
  const start = Math.max(0, end - 120);
  const view = s.slice(start, end);
  const padR = 62;
  const botT = 18;
  const volH = Math.round(H * 0.2);
  const chH = H - volH - botT - 12;
  const chT = 6;
  const hi = Math.max(...view.map((d) => d.h));
  const lo = Math.min(...view.map((d) => d.l));
  const pr = (hi - lo) * 0.08 || 1;
  const py = (v: number) => chT + chH * (1 - (v - lo + pr) / (hi - lo + 2 * pr));
  const slotW = (W - padR - 6) / 120;
  const cw = Math.max(2, slotW * 0.62);
  const px = (i: number) => 3 + slotW * (i - start) + slotW / 2;

  g.strokeStyle = "#1F1F26";
  g.fillStyle = "#5C5E68";
  g.textAlign = "left";
  for (let k = 0; k <= 4; k++) {
    const v = lo - pr + ((hi - lo + 2 * pr) * k) / 4;
    const yy = py(v);
    g.beginPath();
    g.moveTo(0, yy);
    g.lineTo(W - padR + 6, yy);
    g.stroke();
    g.fillText(Math.round(v).toLocaleString("ko-KR"), W - padR + 10, yy + 4);
  }

  const vmax = Math.max(...view.map((d) => d.v));
  view.forEach((d, j) => {
    const i = start + j;
    const xx = px(i);
    const up = d.c >= d.o;
    const col = up ? UP : DOWN;
    g.strokeStyle = col;
    g.fillStyle = col;
    g.beginPath();
    g.moveTo(xx, py(d.h));
    g.lineTo(xx, py(d.l));
    g.stroke();
    const yo = py(d.o);
    const yc = py(d.c);
    g.fillRect(xx - cw / 2, Math.min(yo, yc), cw, Math.max(1, Math.abs(yc - yo)));
    const vh = (d.v / vmax) * (volH - 6);
    g.globalAlpha = 0.55;
    g.fillRect(xx - cw / 2, H - botT - vh, cw, vh);
    g.globalAlpha = 1;
  });

  const last = view[view.length - 1];
  if (last) {
    const yy = py(last.c);
    g.strokeStyle = "#E8E8EC";
    g.setLineDash([3, 3]);
    g.beginPath();
    g.moveTo(0, yy);
    g.lineTo(W - padR + 6, yy);
    g.stroke();
    g.setLineDash([]);
    g.fillStyle = last.c >= s[0].o ? UP : DOWN;
    g.fillRect(W - padR + 6, yy - 9, padR - 8, 18);
    g.fillStyle = "#fff";
    g.textAlign = "left";
    g.fillText(last.c.toLocaleString("ko-KR"), W - padR + 10, yy + 4);
  }

  for (const t of trades) {
    if (t.i < start || t.i >= end) continue;
    const xx = px(t.i);
    const d = s[t.i];
    const buy = t.side === "buy";
    const yy = buy ? py(d.l) + 14 : py(d.h) - 14;
    g.fillStyle = buy ? UP : DOWN;
    g.beginPath();
    g.arc(xx, yy, 8, 0, 7);
    g.fill();
    g.fillStyle = "#fff";
    g.textAlign = "center";
    g.font = "bold 10px Pretendard, sans-serif";
    g.fillText(buy ? "B" : "S", xx, yy + 3.5);
    g.font = "11px Pretendard, sans-serif";
  }

  g.fillStyle = "#5C5E68";
  g.textAlign = "center";
  for (let i = start; i < end; i++) {
    const m = 540 + i;
    if (m % 60 === 0) g.fillText(String(Math.floor(m / 60)).padStart(2, "0") + ":00", px(i), H - 4);
  }
}

export default function Replay({
  initialStock,
  active,
  onPlayingChange,
}: {
  initialStock: string;
  active: boolean;
  onPlayingChange: (p: boolean) => void;
}) {
  const [rDate, setRDate] = useState("2026-07-31");
  const [rStock, setRStock] = useState(initialStock);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(10);
  const [idx, setIdx] = useState(60);
  const [done, setDone] = useState(false);
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [oType, setOType] = useState<"market" | "limit">("market");
  const [qty, setQty] = useState("");
  const [limitPx, setLimitPx] = useState("");
  const [trades, setTrades] = useState<Trade[]>([]);
  const [pos, setPos] = useState({ qty: 0, avg: 0 });
  const [realized, setRealized] = useState(0);
  const [buyTurnover, setBuyTurnover] = useState(0);
  const [toastData, setToastData] = useState<{ msg: string; dot: string } | null>(null);
  const [modal, setModal] = useState(false);

  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const tt = useRef<ReturnType<typeof setTimeout> | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const stopTimer = () => {
    if (timer.current) clearInterval(timer.current);
  };
  const startTimer = (p: boolean, sp: number) => {
    stopTimer();
    if (!p) return;
    timer.current = setInterval(() => {
      setIdx((i) => {
        if (i >= 390) {
          stopTimer();
          setPlaying(false);
          setDone(true);
          return i;
        }
        return i + 1;
      });
    }, SPEED_MS[sp]);
  };
  const pause = () => {
    stopTimer();
    setPlaying(false);
  };
  const resetSession = () => {
    stopTimer();
    setPlaying(false);
    setDone(false);
    setIdx(0);
    setTrades([]);
    setPos({ qty: 0, avg: 0 });
    setRealized(0);
    setBuyTurnover(0);
  };
  const togglePlay = () => {
    if (done) {
      resetSession();
      return;
    }
    const p = !playing;
    setPlaying(p);
    startTimer(p, speed);
  };
  const changeSpeed = (v: number) => {
    setSpeed(v);
    startTimer(playing, v);
  };

  const toast = (msg: string, ok: boolean) => {
    if (tt.current) clearTimeout(tt.current);
    setToastData({ msg, dot: ok ? UP : NEUTRAL });
    tt.current = setTimeout(() => setToastData(null), 2600);
  };

  useEffect(() => {
    onPlayingChange(playing);
  }, [playing, onPlayingChange]);

  useEffect(() => {
    if (!active) pause();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  useEffect(
    () => () => {
      stopTimer();
      if (tt.current) clearTimeout(tt.current);
      onPlayingChange(false);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  useEffect(() => {
    if (!active) return;
    const draw = () => canvasRef.current && drawReplay(canvasRef.current, series(rStock, rDate), idx, trades);
    draw();
    window.addEventListener("resize", draw);
    return () => window.removeEventListener("resize", draw);
  }, [active, rStock, rDate, idx, trades]);

  const st = STOCKS.find((x) => x.code === rStock)!;
  const bars = series(rStock, rDate);
  const cur = bars[Math.min(idx, 390)].c;
  const chg = (cur / bars[0].o - 1) * 100;
  const q = Math.max(0, parseInt(qty) || 0);
  const oPx = oType === "limit" ? parseInt(limitPx) || cur : cur;
  const amt = q * oPx;
  const fee = Math.floor(amt * FEE_RATE);
  const tax = side === "sell" ? Math.floor(amt * SELL_TAX_RATE) : 0;
  const oTotal = side === "buy" ? amt + fee : amt - fee - tax;
  const mins = 540 + Math.min(idx, 390);
  const clock = `${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}`;
  const sumRate = buyTurnover > 0 ? (realized / buyTurnover) * 100 : 0;

  const placeOrder = () => {
    if (!q) {
      toast("수량을 입력하세요", false);
      return;
    }
    if (side === "buy" && st.limitUp) {
      setModal(true);
      return;
    }
    if (side === "buy") {
      setPos((p) => ({ qty: p.qty + q, avg: (p.avg * p.qty + oPx * q) / (p.qty + q) }));
      setBuyTurnover((t) => t + oPx * q);
    } else {
      if (q > pos.qty) {
        toast("보유 수량이 부족합니다", false);
        return;
      }
      setRealized((r) => r + (oPx - pos.avg) * q);
      setPos((p) => ({ qty: p.qty - q, avg: p.qty - q > 0 ? p.avg : 0 }));
    }
    setTrades((t) => [...t, { i: idx, side, px: oPx, qty: q }]);
    setQty("");
    toast((side === "buy" ? "매수" : "매도") + " 체결 · " + st.name + " " + q + "주 @ " + won(oPx), true);
  };

  const rowStyle: React.CSSProperties = { display: "flex", justifyContent: "space-between" };

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 1240 }}>
      <div className="card" style={{ padding: "12px 16px", display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <select
          className="select"
          value={rDate}
          onChange={(e) => {
            setRDate(e.target.value);
            resetSession();
          }}
        >
          {["2026-07-31", "2026-07-30", "2026-07-29"].map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <select
          className="select"
          style={{ minWidth: 150 }}
          value={rStock}
          onChange={(e) => {
            setRStock(e.target.value);
            resetSession();
          }}
        >
          {STOCKS.map((s) => (
            <option key={s.code} value={s.code}>
              {s.name}
            </option>
          ))}
        </select>
        <button className="btnAccent" onClick={togglePlay}>
          {done ? "↺ 다시 재생" : playing ? "⏸ 일시정지" : "▶ 재생"}
        </button>
        <div style={{ display: "flex", gap: 4, background: "#111114", borderRadius: 9, padding: 3 }}>
          {[1, 10, 60].map((v) => (
            <button key={v} onClick={() => changeSpeed(v)} style={seg(speed === v)}>
              {v}x
            </button>
          ))}
        </div>
        <input
          type="range"
          className="scrub"
          min={0}
          max={390}
          value={idx}
          onChange={(e) => {
            const v = +e.target.value;
            setIdx(v);
            setDone(v >= 390);
          }}
          style={{ flex: 1, minWidth: 160 }}
        />
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, flex: "none" }}>
          <span style={{ fontSize: 20, fontWeight: 800, letterSpacing: "-0.3px" }}>{clock}</span>
          <span style={{ fontSize: 11, color: "#5C5E68" }}>/ 15:30</span>
        </div>
      </div>

      {done && (
        <div className="card" style={{ borderColor: "rgba(240,68,82,0.4)", padding: "16px 20px", display: "flex", alignItems: "center", gap: 32 }}>
          <span style={{ fontSize: 14, fontWeight: 700 }}>세션 종료 · 결과 요약</span>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontSize: 11, color: "#8B8D98" }}>실현손익</span>
            <span style={{ fontSize: 18, fontWeight: 700, color: clr(realized) }}>{sgnWon(realized)}</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontSize: 11, color: "#8B8D98" }}>수익률</span>
            <span style={{ fontSize: 18, fontWeight: 700, color: clr(realized) }}>{pct(sumRate)}</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontSize: 11, color: "#8B8D98" }}>매매 횟수</span>
            <span style={{ fontSize: 18, fontWeight: 700 }}>{trades.length}회</span>
          </div>
          <div style={{ flex: 1 }} />
          <button className="btnGhost" onClick={resetSession}>
            다시 재생
          </button>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 14, alignItems: "start" }}>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 10, minWidth: 0 }}>
            <span style={{ fontSize: 15, fontWeight: 700, whiteSpace: "nowrap", flex: "none" }}>{st.name}</span>
            <span style={{ fontSize: 12, color: "#5C5E68", whiteSpace: "nowrap", flex: "none" }}>{rStock}</span>
            <span style={{ fontSize: 18, fontWeight: 800, color: clr(chg), whiteSpace: "nowrap", flex: "none" }}>{won(cur)}</span>
            <span style={{ fontSize: 13, fontWeight: 600, color: clr(chg), whiteSpace: "nowrap", flex: "none" }}>{pct(chg)}</span>
            <div style={{ flex: 1 }} />
            <span style={{ fontSize: 11, color: "#5C5E68" }}>1분봉 · 최근 120봉</span>
          </div>
          <canvas ref={canvasRef} style={{ width: "100%", height: 430, display: "block" }} />
        </div>

        <div className="card" style={{ padding: 16, position: "sticky", top: 76, display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", gap: 4, background: "#111114", borderRadius: 9, padding: 3 }}>
            <button onClick={() => setSide("buy")} style={{ ...seg(side === "buy", UP), flex: 1, height: 34, fontSize: 13 }}>
              매수
            </button>
            <button onClick={() => setSide("sell")} style={{ ...seg(side === "sell", DOWN), flex: 1, height: 34, fontSize: 13 }}>
              매도
            </button>
          </div>
          <div style={{ display: "flex", gap: 4 }}>
            <button
              onClick={() => setOType("market")}
              style={{ ...seg(oType === "market"), flex: 1, border: "1px solid " + (oType === "market" ? "#3C3C46" : "#26262E"), background: oType === "market" ? "#26262E" : "#111114" }}
            >
              시장가
            </button>
            <button
              onClick={() => {
                setOType("limit");
                setLimitPx((p) => p || String(cur));
              }}
              style={{ ...seg(oType === "limit"), flex: 1, border: "1px solid " + (oType === "limit" ? "#3C3C46" : "#26262E"), background: oType === "limit" ? "#26262E" : "#111114" }}
            >
              지정가
            </button>
          </div>
          {oType === "limit" && (
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
              <span style={{ color: "#8B8D98" }}>체결단가</span>
              <span>{won(oPx)}</span>
            </div>
            <div style={rowStyle}>
              <span style={{ color: "#8B8D98" }}>주문금액</span>
              <span>{won(amt)}</span>
            </div>
            <div style={rowStyle}>
              <span style={{ color: "#8B8D98" }}>수수료 (0.015%)</span>
              <span>{won(fee)}</span>
            </div>
            <div style={rowStyle}>
              <span style={{ color: "#8B8D98" }}>거래세 (0.15%)</span>
              <span>{side === "sell" ? won(tax) : "—"}</span>
            </div>
            <div style={{ height: 1, background: "#26262E", margin: "2px 0" }} />
            <div style={{ ...rowStyle, fontSize: 13, fontWeight: 700 }}>
              <span>{side === "buy" ? "총 매수금액" : "총 매도금액(세후)"}</span>
              <span style={{ color: side === "buy" ? UP : DOWN }}>{won(oTotal)}</span>
            </div>
          </div>
          <div style={{ fontSize: 12, color: "#8B8D98", display: "flex", justifyContent: "space-between" }}>
            <span>보유</span>
            <span>{pos.qty > 0 ? `${pos.qty.toLocaleString("ko-KR")}주 · 평단 ${won(pos.avg)}` : "없음"}</span>
          </div>
          <button
            onClick={placeOrder}
            style={{ height: 42, borderRadius: 10, border: "none", cursor: "pointer", fontSize: 14, fontWeight: 700, color: "#fff", background: side === "buy" ? UP : DOWN }}
          >
            {st.name} {side === "buy" ? "매수" : "매도"}
          </button>
        </div>
      </div>

      {toastData && (
        <div
          style={{
            position: "fixed",
            bottom: 28,
            left: "50%",
            transform: "translateX(-50%)",
            background: "#22222A",
            border: "1px solid #2C2C36",
            borderRadius: 12,
            padding: "12px 20px",
            fontSize: 13,
            fontWeight: 600,
            boxShadow: "0 12px 32px rgba(0,0,0,0.5)",
            animation: "toastIn 0.25s ease",
            zIndex: 100,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: toastData.dot }} />
          {toastData.msg}
        </div>
      )}

      {modal && (
        <div
          onClick={() => setModal(false)}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 200, display: "flex", alignItems: "center", justifyContent: "center" }}
        >
          <div style={{ background: "#1A1A20", border: "1px solid #2C2C36", borderRadius: 16, padding: 24, width: 380, display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 22, height: 22, borderRadius: "50%", background: "rgba(240,68,82,0.15)", color: UP, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 13 }}>
                !
              </span>
              <span style={{ fontSize: 15, fontWeight: 700 }}>주문 거부</span>
            </div>
            <p style={{ margin: 0, fontSize: 13, color: "#B7B9C2", lineHeight: 1.6 }}>
              해당 종목은 <span style={{ color: UP, fontWeight: 700 }}>상한가(+30.0%)</span>에 도달하여 매수 주문이
              거부되었습니다. 상한가 종목은 매도 호가가 없어 시장가 매수가 체결되지 않습니다.
            </p>
            <button className="btnAccent" onClick={() => setModal(false)} style={{ height: 38, justifyContent: "center" }}>
              확인
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
