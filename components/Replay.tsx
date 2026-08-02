"use client";

// 리플레이 — 서버 세션 기반. 커서(가상 시각)는 서버 DB에만 있고 tick으로만
// 전진한다. 클라이언트는 커서 이전 분봉만 받는다(룩어헤드 서버 강제).
import { useCallback, useEffect, useRef, useState } from "react";
import type { Bar } from "@/lib/engine/types";
import { clr, DOWN, pct, sgnWon, UP, won } from "@/lib/format";
import { seg, setupCanvas } from "@/lib/ui";
import OrderPanel, { type OrderReqUi } from "./OrderPanel";
import { j, post, type StockRow } from "./client";

type Trade = { ts: string; side: "BUY" | "SELL" };
type Session = {
  id: number;
  cursor: string;
  cash: number;
  initialCash: number;
  status: string;
  result: { equity: number; returnPct: number; trades: number } | null;
  positions: { ticker: string; qty: number; avgPrice: number }[];
};
type Fill = {
  orderId: number; ticker: string; side: "BUY" | "SELL";
  status: "FILLED" | "REJECTED"; reason?: string; price?: number; qty?: number; ts?: string;
};

// 배속: [실제 간격 ms, 요청당 가상 분] — 1x=분당 0.9초, 60x=분당 ~16ms
const SPEED_BATCH: Record<number, [number, number]> = { 1: [900, 1], 10: [450, 5], 60: [500, 30] };

const minutesFrom9 = (ts: string) => {
  const [h, m] = ts.slice(11).split(":").map(Number);
  return h * 60 + m - 540;
};

function drawReplay(cv: HTMLCanvasElement, s: Bar[], trades: Trade[]) {
  const c = setupCanvas(cv);
  if (!c) return;
  const { g, W, H } = c;
  g.clearRect(0, 0, W, H);
  const view = s.slice(-120);
  if (!view.length) {
    g.fillStyle = "#5C5E68";
    g.textAlign = "center";
    g.fillText("재생을 시작하면 분봉이 표시됩니다", W / 2, H / 2);
    return;
  }
  const start = s.length - view.length;
  const padR = 62;
  const botT = 18;
  const volH = Math.round(H * 0.2);
  const chH = H - volH - botT - 12;
  const chT = 6;
  const hi = Math.max(...view.map((d) => d.high));
  const lo = Math.min(...view.map((d) => d.low));
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
  const vmax = Math.max(...view.map((d) => d.volume), 1);
  const tradeAt = new Map(trades.map((t) => [t.ts, t.side]));
  view.forEach((d, jj) => {
    const i = start + jj;
    const xx = px(i);
    const up = d.close >= d.open;
    const col = up ? UP : DOWN;
    g.strokeStyle = col;
    g.fillStyle = col;
    g.beginPath();
    g.moveTo(xx, py(d.high));
    g.lineTo(xx, py(d.low));
    g.stroke();
    const yo = py(d.open);
    const yc = py(d.close);
    g.fillRect(xx - cw / 2, Math.min(yo, yc), cw, Math.max(1, Math.abs(yc - yo)));
    const vh = (d.volume / vmax) * (volH - 6);
    g.globalAlpha = 0.55;
    g.fillRect(xx - cw / 2, H - botT - vh, cw, vh);
    g.globalAlpha = 1;
    const side = tradeAt.get(d.ts);
    if (side) {
      const buy = side === "BUY";
      const yy = buy ? py(d.low) + 14 : py(d.high) - 14;
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
  });
  const last = view[view.length - 1];
  const yy = py(last.close);
  g.strokeStyle = "#E8E8EC";
  g.setLineDash([3, 3]);
  g.beginPath();
  g.moveTo(0, yy);
  g.lineTo(W - padR + 6, yy);
  g.stroke();
  g.setLineDash([]);
  g.fillStyle = last.close >= s[0].open ? UP : DOWN;
  g.fillRect(W - padR + 6, yy - 9, padR - 8, 18);
  g.fillStyle = "#fff";
  g.textAlign = "left";
  g.fillText(last.close.toLocaleString("ko-KR"), W - padR + 10, yy + 4);
  g.fillStyle = "#5C5E68";
  g.textAlign = "center";
  for (let i = start; i < s.length; i++) {
    const m = 540 + minutesFrom9(s[i].ts);
    if (m % 60 === 0) g.fillText(String(Math.floor(m / 60)).padStart(2, "0") + ":00", px(i), H - 4);
  }
}

export default function Replay({
  initialStock,
  active,
  onPlayingChange,
  notify,
}: {
  initialStock: string;
  active: boolean;
  onPlayingChange: (p: boolean) => void;
  notify: (msg: string, ok: boolean) => void;
}) {
  const [dates, setDates] = useState<string[]>([]);
  const [date, setDate] = useState("");
  const [ticker, setTicker] = useState(initialStock);
  const [stockName, setStockName] = useState(initialStock);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<StockRow[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [bars, setBars] = useState<Bar[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(10);
  const [modal, setModal] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const inflight = useRef(false);
  const createdKey = useRef(""); // StrictMode 이펙트 2회 실행으로 인한 세션 중복 생성 방지
  const epoch = useRef(0); // 세션 교체 세대 — inflight 응답이 옛 세션 상태를 되살리는 것 방지

  // 리플레이 가능한 일자 — 서버가 parquet 존재만 확인해 한 번에 돌려준다
  useEffect(() => {
    j<{ dates: string[] }>("/api/v1/replay/dates")
      .then((r) => {
        setDates(r.dates);
        if (r.dates.length) setDate((cur) => cur || r.dates[0]);
      })
      .catch(() => notify("리플레이 가능 일자 조회 실패", false));
  }, [notify]);

  // 종목 검색
  useEffect(() => {
    const t = q.trim();
    if (!t) return setResults([]);
    const h = setTimeout(async () => {
      try {
        const r = await j<{ results: StockRow[] }>(`/api/v1/stocks/search?q=${encodeURIComponent(t)}`);
        setResults(r.results.slice(0, 6));
      } catch {
        /* ignore */
      }
    }, 250);
    return () => clearTimeout(h);
  }, [q]);

  useEffect(() => {
    setTicker(initialStock);
  }, [initialStock]);

  const stopTimer = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  }, []);
  const pause = useCallback(() => {
    stopTimer();
    setPlaying(false);
    onPlayingChange(false);
  }, [stopTimer, onPlayingChange]);

  const refreshSession = useCallback(async (id: number, e?: number) => {
    const s = await j<Session>(`/api/v1/replay/${id}`);
    if (e === undefined || epoch.current === e) setSession(s);
    return s;
  }, []);

  const refreshBars = useCallback(
    async (id: number, e?: number) => {
      const r = await j<{ bars: Bar[] }>(`/api/v1/stocks/${ticker}/minutes?session=${id}`);
      if (e === undefined || epoch.current === e) setBars(r.bars);
    },
    [ticker],
  );

  // 날짜·종목 확정 → 새 세션. active 가드: 숨겨진 상태(다른 화면)에서
  // detailTicker 동기화로 세션이 파괴·양산되는 것 방지 — 리플레이 화면일 때만 반영.
  useEffect(() => {
    if (!active || !date || !ticker) return;
    const key = `${date}|${ticker}`;
    if (createdKey.current === key) return;
    createdKey.current = key;
    epoch.current++;
    let dead = false;
    pause();
    setSession(null);
    setBars([]);
    setTrades([]);
    (async () => {
      const name = await j<{ results: StockRow[] }>(`/api/v1/stocks/search?q=${ticker}`)
        .then((r) => r.results[0]?.name ?? ticker)
        .catch(() => ticker);
      const created = await post<{ id: number }>("/api/v1/replay/sessions", {
        date,
        tickers: [ticker],
        name: `${date} ${name}`,
      });
      if (dead) return;
      setStockName(name);
      await refreshSession(created.id);
      await refreshBars(created.id);
    })().catch((e) => {
      if (!dead) notify(e instanceof Error ? e.message : String(e), false);
    });
    return () => {
      dead = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, date, ticker]);

  const applyFills = useCallback(
    (fills: Fill[]) => {
      for (const f of fills) {
        if (f.status === "FILLED" && f.ts) {
          setTrades((t) => [...t, { ts: f.ts!, side: f.side }]);
          notify(`${f.side === "BUY" ? "매수" : "매도"} 체결 · ${f.qty}주 @ ${won(f.price!)}`, true);
        } else if (f.status === "REJECTED") {
          if (f.reason === "상한가" || f.reason === "하한가") setModal(f.reason);
          else notify(`주문 거부 · ${f.reason}`, false);
        }
      }
    },
    [notify],
  );

  const doTick = useCallback(
    async (minutes: number, finish = false) => {
      if (!session || inflight.current) return null;
      const e = epoch.current; // 이 tick이 속한 세션 세대 — 교체되면 응답 폐기
      const id = session.id;
      inflight.current = true;
      try {
        const r = await post<{ cursor: string; fills: Fill[]; result: Session["result"] }>(
          `/api/v1/replay/${id}/tick`,
          { minutes, finish },
        );
        if (epoch.current !== e) return null;
        applyFills(r.fills);
        await refreshBars(id, e);
        const s = await refreshSession(id, e);
        if (epoch.current !== e) return null;
        if (r.cursor >= `${date} 15:30` && !finish && s.status === "ACTIVE") {
          pause();
          await post(`/api/v1/replay/${id}/tick`, { minutes: 1, finish: true });
          if (epoch.current !== e) return null;
          await refreshSession(id, e);
        }
        return r;
      } finally {
        inflight.current = false;
      }
    },
    [session, date, applyFills, refreshBars, refreshSession, pause],
  );

  const startTimer = useCallback(
    (sp: number) => {
      stopTimer();
      const [ms, mins] = SPEED_BATCH[sp];
      timer.current = setInterval(() => {
        doTick(mins).catch(() => {});
      }, ms);
    },
    [doTick, stopTimer],
  );

  const togglePlay = () => {
    if (!session || session.status !== "ACTIVE") return;
    if (playing) return pause();
    setPlaying(true);
    onPlayingChange(true);
    startTimer(speed);
  };

  const changeSpeed = (v: number) => {
    setSpeed(v);
    if (playing) startTimer(v);
  };

  useEffect(() => {
    if (!active) pause();
  }, [active, pause]);
  useEffect(() => () => stopTimer(), [stopTimer]);

  useEffect(() => {
    if (!active) return;
    const draw = () => canvasRef.current && drawReplay(canvasRef.current, bars, trades);
    draw();
    window.addEventListener("resize", draw);
    return () => window.removeEventListener("resize", draw);
  }, [active, bars, trades]);

  const cursorMin = session ? Math.max(0, minutesFrom9(session.cursor)) : 0;
  // 스크럽: 재생을 멈추고 서버 커서를 재조회해 델타 계산 — stale 커서로 인한 오버슈트 방지
  const onScrub = async (target: number) => {
    if (!session || session.status !== "ACTIVE" || inflight.current) return;
    pause();
    const s = await refreshSession(session.id);
    const cur = Math.max(0, minutesFrom9(s.cursor));
    if (target <= cur) return notify("되감기는 새 세션으로 시작하세요 (날짜·종목 재선택)", false);
    await doTick(target - cur);
  };

  const submitOrder = async (req: OrderReqUi) => {
    if (!session) return notify("세션 준비 중", false);
    if (session.status !== "ACTIVE") return notify("종료된 세션입니다", false);
    if (!req.qty) return notify("수량을 입력하세요", false);
    try {
      const r = await post<{ status: string; rejectReason?: string }>(
        `/api/v1/replay/${session.id}/orders`,
        { ticker, ...req },
      );
      if (r.status === "REJECTED") {
        if (r.rejectReason === "상한가" || r.rejectReason === "하한가") setModal(r.rejectReason);
        else notify(`주문 거부 · ${r.rejectReason}`, false);
      } else {
        notify("주문 접수 — 다음 분봉에서 체결 판정", true);
      }
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e), false);
    }
  };

  const last = bars[bars.length - 1];
  const chg = last && bars[0] ? (last.close / bars[0].open - 1) * 100 : 0;
  const clock = session ? session.cursor.slice(11) : "09:00";
  const position = session?.positions.find((p) => p.ticker === ticker) ?? null;
  const done = session?.status === "FINISHED";

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 1240 }}>
      <div className="card" style={{ padding: "12px 16px", display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <select className="select" value={date} onChange={(e) => setDate(e.target.value)}>
          {dates.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
        <div style={{ position: "relative", minWidth: 170 }}>
          <input
            className="input"
            style={{ height: 34, fontSize: 13, width: 170 }}
            placeholder={`${stockName} (${ticker})`}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          {results.length > 0 && (
            <div style={{ position: "absolute", top: 38, left: 0, right: 0, background: "#1A1A20", border: "1px solid #2C2C36", borderRadius: 10, overflow: "hidden", zIndex: 20 }}>
              {results.map((r) => (
                <div
                  key={r.ticker}
                  className="rowHover"
                  style={{ display: "flex", justifyContent: "space-between", padding: "8px 10px", cursor: "pointer", fontSize: 12 }}
                  onClick={() => {
                    setQ("");
                    setResults([]);
                    setTicker(r.ticker);
                  }}
                >
                  <span style={{ fontWeight: 600 }}>{r.name}</span>
                  <span style={{ color: "#8B8D98" }}>{r.ticker}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <button className="btnAccent" onClick={togglePlay} disabled={!session || done}>
          {done ? "종료됨" : playing ? "⏸ 일시정지" : "▶ 재생"}
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
          value={cursorMin}
          onChange={(e) => onScrub(Number(e.target.value))}
          style={{ flex: 1, minWidth: 160 }}
        />
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, flex: "none" }}>
          <span style={{ fontSize: 20, fontWeight: 800, letterSpacing: "-0.3px" }}>{clock}</span>
          <span style={{ fontSize: 11, color: "#5C5E68" }}>/ 15:30</span>
        </div>
      </div>

      {done && session?.result && (
        <div className="card" style={{ borderColor: "rgba(240,68,82,0.4)", padding: "16px 20px", display: "flex", alignItems: "center", gap: 32 }}>
          <span style={{ fontSize: 14, fontWeight: 700 }}>세션 종료 · 결과 요약</span>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontSize: 11, color: "#8B8D98" }}>평가손익</span>
            <span style={{ fontSize: 18, fontWeight: 700, color: clr(session.result.equity - session.initialCash) }}>
              {sgnWon(session.result.equity - session.initialCash)}
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontSize: 11, color: "#8B8D98" }}>수익률</span>
            <span style={{ fontSize: 18, fontWeight: 700, color: clr(session.result.returnPct) }}>{pct(session.result.returnPct)}</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontSize: 11, color: "#8B8D98" }}>체결 횟수</span>
            <span style={{ fontSize: 18, fontWeight: 700 }}>{session.result.trades}회</span>
          </div>
          <div style={{ flex: 1 }} />
          <button className="btnGhost" onClick={() => setTicker((t) => t)} disabled>
            결과는 세션 목록에 저장됨
          </button>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 14, alignItems: "start" }}>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 10, minWidth: 0 }}>
            <span style={{ fontSize: 15, fontWeight: 700, whiteSpace: "nowrap", flex: "none" }}>{stockName}</span>
            <span style={{ fontSize: 12, color: "#5C5E68", whiteSpace: "nowrap", flex: "none" }}>{ticker}</span>
            {last && (
              <>
                <span style={{ fontSize: 18, fontWeight: 800, color: clr(chg), whiteSpace: "nowrap", flex: "none" }}>{won(last.close)}</span>
                <span style={{ fontSize: 13, fontWeight: 600, color: clr(chg), whiteSpace: "nowrap", flex: "none" }}>{pct(chg)}</span>
              </>
            )}
            <div style={{ flex: 1 }} />
            <span style={{ fontSize: 11, color: "#5C5E68" }}>
              현금 {session ? won(session.cash) : "—"} · 1분봉 최근 120봉
            </span>
          </div>
          <canvas ref={canvasRef} style={{ width: "100%", height: 430, display: "block" }} />
        </div>

        <div style={{ position: "sticky", top: 76 }}>
          <OrderPanel
            stockName={stockName}
            refPrice={last?.close ?? null}
            position={position}
            disabled={!session || done}
            note="체결: 다음 1분봉 시가 + 슬리피지 5bp (지정가는 고저 터치)"
            onSubmit={submitOrder}
          />
        </div>
      </div>

      {modal && (
        <div
          onClick={() => setModal(null)}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 200, display: "flex", alignItems: "center", justifyContent: "center" }}
        >
          <div style={{ background: "#1A1A20", border: "1px solid #2C2C36", borderRadius: 16, padding: 24, width: 380, display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 22, height: 22, borderRadius: "50%", background: "rgba(240,68,82,0.15)", color: UP, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 13 }}>
                !
              </span>
              <span style={{ fontSize: 15, fontWeight: 700 }}>주문 거부 · {modal}</span>
            </div>
            <p style={{ margin: 0, fontSize: 13, color: "#B7B9C2", lineHeight: 1.6 }}>
              {modal === "상한가"
                ? "해당 분봉이 상한가(+30%) 상태라 매수가 체결되지 않았습니다. 상한가에서는 매도 호가가 없어 시장가 매수가 불가능합니다."
                : "해당 분봉이 하한가(−30%) 상태라 매도가 체결되지 않았습니다. 하한가에서는 매수 호가가 없어 시장가 매도가 불가능합니다."}
            </p>
            <button className="btnAccent" onClick={() => setModal(null)} style={{ height: 38, justifyContent: "center" }}>
              확인
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
