"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { NEUTRAL, UP } from "@/lib/format";
import { isMarketOpen } from "@/lib/market-hours";
import Dashboard from "@/components/Dashboard";
import StockDetail from "@/components/StockDetail";
import Orders from "@/components/Orders";
import AiLog from "@/components/AiLog";
import { j, post, type StockRow } from "@/components/client";

type Screen = "dash" | "detail" | "orders" | "ai";
type Account = { id: number; name: string; initial_cash: number; cash: number };

const NAV: { key: Screen; label: string }[] = [
  { key: "dash", label: "대시보드" },
  { key: "detail", label: "종목 상세" },
  { key: "orders", label: "주문·체결" },
  { key: "ai", label: "AI 판단 로그" },
];

export default function App() {
  const [screen, setScreen] = useState<Screen>("dash");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<StockRow[]>([]);
  const [detailTicker, setDetailTicker] = useState("005930");
  const [toast, setToast] = useState<{ msg: string; dot: string } | null>(null);

  const notify = useCallback((msg: string, ok: boolean) => {
    setToast({ msg, dot: ok ? UP : NEUTRAL });
    setTimeout(() => setToast(null), 2600);
  }, []);

  // 계좌 부트스트랩 — 없으면 기본 계좌 자동 생성 (1인용)
  const bootstrapped = useRef(false); // StrictMode 2회 실행 → 계좌 중복 생성 방지
  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    (async () => {
      let list = (await j<{ accounts: Account[] }>("/api/v1/accounts")).accounts;
      if (!list.length) {
        await post("/api/v1/accounts", { name: "기본 계좌", initialCash: 10_000_000 });
        list = (await j<{ accounts: Account[] }>("/api/v1/accounts")).accounts;
      }
      setAccounts(list);
      setAccountId((cur) => cur ?? list[0]?.id ?? null);
    })().catch(() => notify("계좌 로드 실패 — Turso 연결 확인", false));
  }, [notify]);

  // 헤더 종목 검색
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

  const openStock = (ticker: string) => {
    setQ("");
    setResults([]);
    setDetailTicker(ticker);
    setScreen("detail");
  };

  const account = accounts.find((a) => a.id === accountId) ?? null;
  const marketOpen = isMarketOpen();
  const statusLabel = marketOpen ? "장중" : "장마감";
  const statusColor = marketOpen ? "#4CAF7D" : "#5C5E68";

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
      <header
        style={{
          height: 56, display: "flex", alignItems: "center", gap: 20, padding: "0 20px",
          background: "#111114", borderBottom: "1px solid #1F1F26", position: "sticky", top: 0, zIndex: 50,
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
            <div style={{ position: "absolute", top: 40, left: 0, right: 0, background: "#1A1A20", border: "1px solid #2C2C36", borderRadius: 12, overflow: "hidden", boxShadow: "0 12px 32px rgba(0,0,0,0.5)", zIndex: 60 }}>
              {results.map((r) => (
                <div
                  key={r.ticker}
                  className="rowHover"
                  onClick={() => openStock(r.ticker)}
                  style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 12px", cursor: "pointer", fontSize: 13 }}
                >
                  <span style={{ fontWeight: 600 }}>{r.name}</span>
                  <span style={{ color: "#8B8D98", fontSize: 12 }}>
                    {r.ticker} · {r.market}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#8B8D98" }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: statusColor }} />
          <span>{statusLabel}</span>
        </div>
        <select
          className="select"
          style={{ background: "#1A1A20", borderRadius: 10, padding: "0 12px" }}
          value={accountId ?? ""}
          onChange={(e) => setAccountId(Number(e.target.value))}
        >
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} (#{a.id})
            </option>
          ))}
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
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "9px 12px", borderRadius: 9, fontSize: 13, cursor: "pointer",
                fontWeight: screen === n.key ? 700 : 500,
                color: screen === n.key ? "#E8E8EC" : "#8B8D98",
                ...(screen === n.key ? { background: "#1F1F26" } : {}),
              }}
            >
              <span>{n.label}</span>
            </div>
          ))}
        </nav>

        <main style={{ flex: 1, minWidth: 0, padding: "20px 24px 32px" }}>
          <div style={{ display: screen === "dash" ? undefined : "none" }}>
            <Dashboard account={account} active={screen === "dash"} onOpenStock={openStock} />
          </div>
          <div style={{ display: screen === "detail" ? undefined : "none" }}>
            <StockDetail ticker={detailTicker} account={account} active={screen === "detail"} notify={notify} />
          </div>
          <div style={{ display: screen === "orders" ? undefined : "none" }}>
            <Orders accountId={accountId} active={screen === "orders"} />
          </div>
          <div style={{ display: screen === "ai" ? undefined : "none" }}>
            <AiLog active={screen === "ai"} />
          </div>
        </main>
      </div>

      {toast && (
        <div
          style={{
            position: "fixed", bottom: 28, left: "50%", transform: "translateX(-50%)",
            background: "#22222A", border: "1px solid #2C2C36", borderRadius: 12, padding: "12px 20px",
            fontSize: 13, fontWeight: 600, boxShadow: "0 12px 32px rgba(0,0,0,0.5)",
            animation: "toastIn 0.25s ease", zIndex: 100, display: "flex", alignItems: "center", gap: 8,
          }}
        >
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: toast.dot }} />
          {toast.msg}
        </div>
      )}
    </div>
  );
}
