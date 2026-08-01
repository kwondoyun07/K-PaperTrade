-- trading: 계좌·주문·판단 DB
-- owner_type/owner_id: 라이브 계좌('ACCOUNT' → accounts.id)와
-- 리플레이 세션('REPLAY' → replay_sessions.id)이 동일 체결 엔진·테이블을 공유한다.

CREATE TABLE IF NOT EXISTS accounts (
  id           INTEGER PRIMARY KEY,
  name         TEXT NOT NULL,
  initial_cash INTEGER NOT NULL,          -- 원 단위
  cash         INTEGER NOT NULL,
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS replay_sessions (
  id           INTEGER PRIMARY KEY,
  name         TEXT,
  date         TEXT NOT NULL,             -- 리플레이 대상 거래일 'YYYY-MM-DD'
  tickers      TEXT NOT NULL,             -- JSON 배열 '["005930", ...]'
  cursor_ts    TEXT,                      -- 현재 가상 시각. 서버가 이 이후 데이터를 내려주지 않는다(룩어헤드 차단)
  initial_cash INTEGER NOT NULL,
  cash         INTEGER NOT NULL,
  status       TEXT NOT NULL DEFAULT 'ACTIVE'
               CHECK (status IN ('ACTIVE','FINISHED')),
  result_json  TEXT,                      -- 종료 시 수익률·체결 요약 (세션 간 비교용)
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
  id            INTEGER PRIMARY KEY,
  owner_type    TEXT NOT NULL CHECK (owner_type IN ('ACCOUNT','REPLAY')),
  owner_id      INTEGER NOT NULL,
  ticker        TEXT NOT NULL,
  side          TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
  order_type    TEXT NOT NULL CHECK (order_type IN ('MARKET','LIMIT')),
  qty           INTEGER NOT NULL,
  limit_price   INTEGER,                  -- LIMIT 주문만
  status        TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING','FILLED','REJECTED','CANCELLED')),
  reject_reason TEXT,                     -- '상한가' | '하한가' | '거래량0' 등
  ordered_at    TEXT NOT NULL,            -- 주문 시각 (리플레이면 가상 시각) KST
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_owner ON orders (owner_type, owner_id);

CREATE TABLE IF NOT EXISTS executions (
  id          INTEGER PRIMARY KEY,
  order_id    INTEGER NOT NULL REFERENCES orders(id),
  price       INTEGER NOT NULL,           -- 슬리피지 반영 체결가 (원)
  qty         INTEGER NOT NULL,
  commission  INTEGER NOT NULL,
  tax         INTEGER NOT NULL,           -- 매도 거래세
  executed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_executions_order ON executions (order_id);

CREATE TABLE IF NOT EXISTS positions (
  owner_type TEXT NOT NULL CHECK (owner_type IN ('ACCOUNT','REPLAY')),
  owner_id   INTEGER NOT NULL,
  ticker     TEXT NOT NULL,
  qty        INTEGER NOT NULL,
  avg_price  INTEGER NOT NULL,
  PRIMARY KEY (owner_type, owner_id, ticker)
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
  owner_type TEXT NOT NULL CHECK (owner_type IN ('ACCOUNT','REPLAY')),
  owner_id   INTEGER NOT NULL,
  ts         TEXT NOT NULL,
  equity     INTEGER NOT NULL,            -- 현금 + 평가금액 (원)
  cash       INTEGER NOT NULL,
  PRIMARY KEY (owner_type, owner_id, ts)
);

CREATE TABLE IF NOT EXISTS ai_decisions (
  id              INTEGER PRIMARY KEY,
  ticker          TEXT NOT NULL,
  ts              TEXT NOT NULL,
  action          TEXT NOT NULL CHECK (action IN ('BUY','SELL','HOLD')),
  reason_summary  TEXT,
  source          TEXT,
  ret_d5          REAL,                   -- 판단 이후 수익률 — 장 마감 배치(6단계)에서 채움
  ret_d20         REAL,
  ret_d60         REAL,
  broker_order_id TEXT                    -- v1.5 키움 모의계좌 미러링 대사용 예약
);
CREATE INDEX IF NOT EXISTS idx_ai_decisions_ticker_ts ON ai_decisions (ticker, ts);
