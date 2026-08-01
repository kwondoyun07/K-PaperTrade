"use client";

// 종목 상세 — 1분봉 캔들차트(lightweight-charts) + 거래량 + 수급 + 주문 패널.
// 장중에는 60초 간격으로 현재 종목만 폴링(quotes 프록시)해 차트를 갱신한다.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  createChart,
  HistogramSeries,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Bar } from "@/lib/engine/types";
import { clr, DOWN, NEUTRAL, pct, sgnWon, UP, won } from "@/lib/format";
import { isMarketOpen, kstDateStr } from "@/lib/market-hours";
import OrderPanel, { type OrderReqUi } from "./OrderPanel";
import { fetchLatestMinutes, j, post, type Portfolio, type StockRow } from "./client";

type Flow = { date: string; individual: number; foreigner: number; institution: number };

const toTime = (ts: string) => (Date.parse(ts.replace(" ", "T") + ":00Z") / 1000) as UTCTimestamp;

export default function StockDetail({
  ticker,
  account,
  active,
  notify,
}: {
  ticker: string;
  account: { id: number } | null;
  active: boolean;
  notify: (msg: string, ok: boolean) => void;
}) {
  const [stock, setStock] = useState<StockRow | null>(null);
  const [bars, setBars] = useState<Bar[]>([]);
  const [date, setDate] = useState<string>("");
  const [flows, setFlows] = useState<Flow[]>([]);
  const [position, setPosition] = useState<{ qty: number; avgPrice: number } | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartApi = useRef<IChartApi | null>(null);
  const tickerRef = useRef(ticker);
  tickerRef.current = ticker;

  const loadPosition = useCallback(async () => {
    if (!account) return;
    const pf = await j<Portfolio>(`/api/v1/accounts/${account.id}/portfolio`);
    if (tickerRef.current !== ticker) return; // 종목 전환 후 도착한 stale 응답 폐기
    const p = pf.positions.find((x) => x.ticker === ticker);
    setPosition(p ? { qty: p.qty, avgPrice: p.avgPrice } : null);
  }, [account, ticker]);

  useEffect(() => {
    if (!active) return;
    let dead = false;
    (async () => {
      const [s, m, f] = await Promise.all([
        j<{ results: StockRow[] }>(`/api/v1/stocks/search?q=${ticker}`),
        fetchLatestMinutes(ticker),
        j<{ flows: Flow[] }>(`/api/v1/stocks/${ticker}/flows?limit=10`),
      ]);
      if (dead) return;
      setStock(s.results[0] ?? { ticker, name: ticker, market: "" });
      setBars(m?.bars ?? []);
      setDate(m?.date ?? "");
      setFlows(f.flows);
      loadPosition().catch(() => {});
    })().catch(() => notify("데이터 로드 실패", false));
    return () => {
      dead = true;
    };
  }, [ticker, active, loadPosition, notify]);

  // 장중 폴링 — 화면에 보이는 이 종목만, 60초 간격
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(async () => {
      if (!isMarketOpen() || document.visibilityState !== "visible") return;
      try {
        await j(`/api/v1/quotes?tickers=${ticker}`);
        const today = kstDateStr();
        const r = await j<{ bars: Bar[] }>(`/api/v1/stocks/${ticker}/minutes?date=${today}`);
        if (r.bars.length) {
          setBars(r.bars);
          setDate(today);
        }
        loadPosition().catch(() => {});
      } catch {
        // 다음 주기에 재시도
      }
    }, 60_000);
    return () => clearInterval(timer);
  }, [ticker, active, loadPosition]);

  // lightweight-charts 렌더
  useEffect(() => {
    if (!active || !chartRef.current) return;
    const el = chartRef.current;
    const chart = createChart(el, {
      height: 430,
      layout: { background: { color: "transparent" }, textColor: "#8B8D98", fontSize: 11 },
      grid: { vertLines: { color: "#1F1F26" }, horzLines: { color: "#1F1F26" } },
      rightPriceScale: { borderColor: "#26262E" },
      timeScale: { borderColor: "#26262E", timeVisible: true, secondsVisible: false },
      crosshair: { horzLine: { color: "#4A4A56" }, vertLine: { color: "#4A4A56" } },
    });
    chartApi.current = chart;
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN,
      wickUpColor: UP, wickDownColor: DOWN,
    });
    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: "vol", priceFormat: { type: "volume" },
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    candles.setData(
      bars.map((b) => ({ time: toTime(b.ts), open: b.open, high: b.high, low: b.low, close: b.close })),
    );
    volume.setData(
      bars.map((b) => ({
        time: toTime(b.ts),
        value: b.volume,
        color: b.close >= b.open ? "rgba(240,68,82,0.45)" : "rgba(49,130,246,0.45)",
      })),
    );
    chart.timeScale().fitContent();
    const resize = () => chart.applyOptions({ width: el.clientWidth });
    resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.remove();
      chartApi.current = null;
    };
  }, [bars, active]);

  const last = bars[bars.length - 1];
  const chg = last && bars[0] ? (last.close / bars[0].open - 1) * 100 : 0;

  const submit = async (req: OrderReqUi) => {
    if (!account) return notify("계좌 없음", false);
    if (!req.qty) return notify("수량을 입력하세요", false);
    try {
      const r = await post<{ status: string; rejectReason?: string }>("/api/v1/orders", {
        accountId: account.id, ticker, ...req,
      });
      if (r.status === "REJECTED") notify(`주문 거부 · ${r.rejectReason}`, false);
      else notify("주문 접수 — 장중 다음 분봉에서 체결됩니다", true);
    } catch (e) {
      notify(String(e instanceof Error ? e.message : e), false);
    }
  };

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 1240 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 14, alignItems: "start" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
          <div className="card" style={{ padding: 16 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 10 }}>
              <span style={{ fontSize: 15, fontWeight: 700, whiteSpace: "nowrap" }}>{stock?.name ?? ticker}</span>
              <span style={{ fontSize: 12, color: "#5C5E68" }}>{ticker}</span>
              {last && (
                <>
                  <span style={{ fontSize: 18, fontWeight: 800, color: clr(chg), whiteSpace: "nowrap" }}>{won(last.close)}</span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: clr(chg), whiteSpace: "nowrap" }}>{pct(chg)} (시가 대비)</span>
                </>
              )}
              <div style={{ flex: 1 }} />
              <span style={{ fontSize: 11, color: "#5C5E68" }}>{date} · 1분봉{isMarketOpen() ? " · 장중 60초 갱신" : ""}</span>
            </div>
            {bars.length ? (
              <div ref={chartRef} style={{ width: "100%" }} />
            ) : (
              <div style={{ height: 430, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, color: "#5C5E68" }}>
                분봉 데이터 없음 — collector 백필 필요 (README 참고)
              </div>
            )}
          </div>

          <div className="card" style={{ padding: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>투자자별 순매수 (원)</div>
            {flows.length ? (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr>
                    {["날짜", "개인", "외국인", "기관"].map((h, i) => (
                      <th key={h} style={{ color: "#8B8D98", fontWeight: 500, padding: "5px 0", borderBottom: "1px solid #1F1F26", textAlign: i ? "right" : "left" }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {flows.map((f) => (
                    <tr key={f.date}>
                      <td style={{ padding: "7px 0", borderBottom: "1px solid #1A1A20", color: "#B7B9C2" }}>{f.date}</td>
                      {[f.individual, f.foreigner, f.institution].map((v, i) => (
                        <td key={i} style={{ padding: "7px 0", borderBottom: "1px solid #1A1A20", textAlign: "right", color: clr(v) }}>
                          {sgnWon(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div style={{ padding: "20px 0", textAlign: "center", fontSize: 12, color: "#5C5E68" }}>
                수급 데이터 없음 — 장 마감 배치(pykrx) 적재 후 표시
              </div>
            )}
          </div>
        </div>

        <div style={{ position: "sticky", top: 76 }}>
          <OrderPanel
            stockName={stock?.name ?? ticker}
            refPrice={last?.close ?? null}
            position={position}
            note={isMarketOpen() ? "체결: 다음 1분봉 시가 + 슬리피지 5bp" : "장마감 — 주문은 접수되며 다음 장중 폴링에서 체결 판정"}
            onSubmit={submit}
          />
        </div>
      </div>
    </section>
  );
}
