// 장중 폴링 프록시 — 화면에서 보고 있는 종목만(최대 10개), 클라이언트 60초 간격.
// 받은 분봉은 Turso 롤링 캐시에 upsert하고, 해당 종목 라이브 PENDING 주문을 정산한다.
import { NextResponse } from "next/server";
import { fetchMinuteBars } from "@/lib/providers/naver";
import { marketDb, tradingDb } from "@/lib/db";
import { prevDayClose } from "@/lib/minutes";
import { settleOwnerOrders } from "@/lib/trading";
import { jerr, qs, todayKst } from "@/lib/api";

const UPSERT =
  "INSERT INTO minute_prices (ticker, ts, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?) " +
  "ON CONFLICT(ticker, ts) DO UPDATE SET open=excluded.open, high=excluded.high, " +
  "low=excluded.low, close=excluded.close, volume=excluded.volume";

export async function GET(req: Request) {
  const raw = qs(req).get("tickers");
  if (!raw) return jerr("tickers 파라미터 필요");
  const tickers = [...new Set(raw.split(",").map((t) => t.trim()).filter(Boolean))].slice(0, 10);
  const date = todayKst();

  const quotes = [];
  for (const ticker of tickers) {
    try {
      const bars = await fetchMinuteBars(ticker, date);
      if (!bars.length) {
        quotes.push({ ticker, price: null }); // 휴장·미거래
        continue;
      }
      // 최근 30봉만 캐시 upsert (쓰기 한도 보호)
      await marketDb().batch(
        bars.slice(-30).map((b) => ({
          sql: UPSERT,
          args: [ticker, b.ts, b.open, b.high, b.low, b.close, b.volume],
        })),
        "write",
      );
      // 이 종목에 PENDING 주문이 있는 라이브 계좌 정산
      const owners = await tradingDb().execute({
        sql: "SELECT DISTINCT owner_id FROM orders WHERE owner_type = 'ACCOUNT' AND status = 'PENDING' AND ticker = ?",
        args: [ticker],
      });
      for (const o of owners.rows) {
        await settleOwnerOrders({ type: "ACCOUNT", id: Number(o.owner_id) });
      }
      const last = bars[bars.length - 1];
      const pdc = await prevDayClose(ticker, date);
      quotes.push({
        ticker,
        ts: last.ts,
        price: last.close,
        open: bars[0].open,
        prevClose: pdc,
        changePct: pdc ? (last.close / pdc - 1) * 100 : null,
      });
    } catch (e) {
      quotes.push({ ticker, price: null, error: String(e) });
    }
  }
  return NextResponse.json({ date, quotes });
}
