-- krx_market: 시세 DB
-- 가격·금액은 원 단위 INTEGER, 시각은 'YYYY-MM-DD HH:MM' KST 텍스트.

CREATE TABLE IF NOT EXISTS stocks (
  ticker     TEXT PRIMARY KEY,            -- '005930'
  name       TEXT NOT NULL,
  market     TEXT NOT NULL,               -- 'KOSPI' | 'KOSDAQ'
  is_active  INTEGER NOT NULL DEFAULT 1,  -- 0 = 상장폐지·거래정지 등 제외 대상
  updated_at TEXT NOT NULL
);

-- 분봉 원본은 GitHub Release parquet에 보관.
-- 이 테이블은 사용자가 조회한 종목의 최근 5거래일 롤링 캐시 전용 (쓰기 한도 보호).
CREATE TABLE IF NOT EXISTS minute_prices (
  ticker TEXT NOT NULL,
  ts     TEXT NOT NULL,                   -- 'YYYY-MM-DD HH:MM' KST
  open   INTEGER NOT NULL,
  high   INTEGER NOT NULL,
  low    INTEGER NOT NULL,
  close  INTEGER NOT NULL,
  volume INTEGER NOT NULL,
  PRIMARY KEY (ticker, ts)
);
CREATE INDEX IF NOT EXISTS idx_minute_prices_ts ON minute_prices (ts); -- 오래된 행 롤링 삭제용

CREATE TABLE IF NOT EXISTS daily_prices (
  ticker TEXT NOT NULL,
  date   TEXT NOT NULL,                   -- 'YYYY-MM-DD'
  open   INTEGER NOT NULL,
  high   INTEGER NOT NULL,
  low    INTEGER NOT NULL,
  close  INTEGER NOT NULL,
  volume INTEGER NOT NULL,
  PRIMARY KEY (ticker, date)
);

-- 투자자별 순매수 (원 단위)
CREATE TABLE IF NOT EXISTS investor_flows (
  ticker      TEXT NOT NULL,
  date        TEXT NOT NULL,
  individual  INTEGER NOT NULL DEFAULT 0,
  foreigner   INTEGER NOT NULL DEFAULT 0,
  institution INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS indices (
  code   TEXT NOT NULL,                   -- 'KOSPI' | 'KOSDAQ'
  date   TEXT NOT NULL,
  open   REAL NOT NULL,                   -- 지수는 소수점 포인트
  high   REAL NOT NULL,
  low    REAL NOT NULL,
  close  REAL NOT NULL,
  volume INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (code, date)
);
