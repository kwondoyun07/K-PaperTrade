"use client";

import { useState } from "react";
import { STOCKS } from "@/lib/sim";
import { UP } from "@/lib/format";
import Dashboard from "@/components/Dashboard";
import Replay from "@/components/Replay";
import Stub from "@/components/Stub";

type Screen = "dash" | "detail" | "replay" | "orders" | "ai";

const NAV: { key: Screen; label: string; soon?: boolean }[] = [
  { key: "dash", label: "대시보드" },
  { key: "detail", label: "종목 상세", soon: true },
  { key: "replay", label: "리플레이" },
  { key: "orders", label: "주문·체결", soon: true },
  { key: "ai", label: "AI 판단 로그", soon: true },
];

const STUBS: Partial<Record<Screen, string>> = {
  detail: "종목 상세",
  orders: "주문·체결 내역",
  ai: "AI 판단 로그",
};

export default function App() {
  const [screen, setScreen] = useState<Screen>("dash");
  const [account, setAccount] = useState("main");
  const [q, setQ] = useState("");
  const [replayStock, setReplayStock] = useState("005930");
  const [replayKey, setReplayKey] = useState(0);
  const [playing, setPlaying] = useState(false);

  const ql = q.trim().toLowerCase();
  const results = ql
    ? STOCKS.filter((s) => s.name.toLowerCase().includes(ql) || s.code.includes(ql)).slice(0, 6)
    : [];

  // 검색에서 종목 선택 → 리플레이 세션을 새로 시작 (key 변경으로 리마운트)
  const goReplay = (code: string) => {
    setQ("");
    setReplayStock(code);
    setReplayKey((k) => k + 1);
    setScreen("replay");
  };

  const live = screen === "replay" && playing;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
      <header
        style={{
          height: 56,
          display: "flex",
          alignItems: "center",
          gap: 20,
          padding: "0 20px",
          background: "#111114",
          borderBottom: "1px solid #1F1F26",
          position: "sticky",
          top: 0,
          zIndex: 50,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "none" }}>
          <div style={{ width: 26, height: 26, borderRadius: 8, background: UP, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 13, color: "#fff" }}>
            K
          </div>
          <span style={{ fontWeight: 700, fontSize: 15, letterSpacing: "-0.2px" }}>K-PaperTrade</span>
          <span style={{ fontSize: 11, fontWeight: 600, color: UP, background: "rgba(240,68,82,0.12)", border: "1px solid rgba(240,68,82,0.35)", padding: "2px 7px", borderRadius: 6, whiteSpace: "nowrap", flex: "none" }}>
            모의투자
          </span>
        </div>
        <div style={{ position: "relative", width: 300, flex: "none" }}>
          <input
            placeholder="종목명·코드 검색"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ width: "100%", height: 34, background: "#1A1A20", border: "1px solid #26262E", borderRadius: 10, color: "#E8E8EC", padding: "0 12px", fontSize: 13 }}
          />
          {results.length > 0 && (
            <div style={{ position: "absolute", top: 40, left: 0, right: 0, background: "#1A1A20", border: "1px solid #2C2C36", borderRadius: 12, overflow: "hidden", boxShadow: "0 12px 32px rgba(0,0,0,0.5)" }}>
              {results.map((r) => (
                <div
                  key={r.code}
                  className="rowHover"
                  onClick={() => goReplay(r.code)}
                  style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 12px", cursor: "pointer", fontSize: 13 }}
                >
                  <span style={{ fontWeight: 600 }}>{r.name}</span>
                  <span style={{ color: "#8B8D98", fontSize: 12 }}>{r.code}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#8B8D98" }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: live ? UP : "#5C5E68" }} />
          <span>{live ? "리플레이 중" : "장마감"}</span>
        </div>
        <select
          className="select"
          style={{ background: "#1A1A20", borderRadius: 10, padding: "0 12px" }}
          value={account}
          onChange={(e) => setAccount(e.target.value)}
        >
          <option value="main">기본 계좌 (00-1234)</option>
          <option value="fresh">신규 계좌 (00-5678)</option>
        </select>
      </header>

      <div style={{ display: "flex", flex: 1, alignItems: "stretch" }}>
        <nav style={{ width: 200, flex: "none", background: "#111114", borderRight: "1px solid #1F1F26", padding: "16px 10px", display: "flex", flexDirection: "column", gap: 2 }}>
          {NAV.map((n) => (
            <div
              key={n.key}
              className="navItem"
              onClick={() => setScreen(n.key)}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "9px 12px",
                borderRadius: 9,
                fontSize: 13,
                cursor: "pointer",
                fontWeight: screen === n.key ? 700 : 500,
                color: screen === n.key ? "#E8E8EC" : "#8B8D98",
                ...(screen === n.key ? { background: "#1F1F26" } : {}),
              }}
            >
              <span>{n.label}</span>
              {n.soon && (
                <span style={{ fontSize: 10, color: "#5C5E68", border: "1px solid #2C2C36", borderRadius: 5, padding: "1px 5px" }}>예정</span>
              )}
            </div>
          ))}
        </nav>

        <main style={{ flex: 1, minWidth: 0, padding: "20px 24px 32px" }}>
          <div style={{ display: screen === "dash" ? undefined : "none" }}>
            <Dashboard account={account} active={screen === "dash"} />
          </div>
          <div style={{ display: screen === "replay" ? undefined : "none" }}>
            <Replay key={replayKey} initialStock={replayStock} active={screen === "replay"} onPlayingChange={setPlaying} />
          </div>
          {STUBS[screen] && <Stub title={STUBS[screen]!} />}
        </main>
      </div>
    </div>
  );
}
