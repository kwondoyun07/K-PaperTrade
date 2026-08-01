# 데이터 파이프라인 (2단계 확정)

## 소스 실측 결과 (2026-08-01 라이브 프로브)

### 네이버 분봉 API (v0 주력, 비공식)

`GET https://api.stock.naver.com/chart/domestic/item/{ticker}/minute`

- 파라미터: `periodSizeMinutes=1`, `startDateTime`/`endDateTime` (YYYYMMDDHHMM)
- 응답: JSON 배열 — `localDateTime`, `openPrice`, `highPrice`, `lowPrice`,
  `currentPrice`(종가), `accumulatedTradingVolume`
- **진짜 분봉 OHLC 제공** (구 fchart.stock.naver.com은 종가·누적량만 — 사용 안 함)
- `accumulatedTradingVolume`은 이름과 달리 **분당 거래량**
  (일합계가 일봉 거래량과 ±0.02% 일치 확인)
- 멀티데이 범위를 한 요청으로 조회 가능 (백필 = 종목당 1요청)
- **제공 범위: 최근 ~6거래일** → 일일 적재를 놓치면 그 날짜 분봉은 영구 유실.
  GitHub Actions cron이 생명선.
- 하루 381봉: 09:00~15:19 연속거래 + 15:30 종가단일가.
  급등일 등엔 장 초반 일부 분봉이 비는 경우 있음(시가단일가 지연 추정).

### pykrx (KRX 정보데이터시스템)

- 벌크 API 3종(전 종목 일봉 by ticker, 투자자별 수급, 지수)이 **빈 응답으로
  실패하는 시간대 존재** (토요일 밤 실측 — KRX 주말 점검 추정, 평일 재확인 필요)
- 종목당 일봉(`get_market_ohlcv_by_date`)은 정상
- `pkg_resources` 의존 → `setuptools<81` 고정 필요

### FinanceDataReader

- `StockListing('KRX')`: 2,872종목 + 최근 거래일 OHLCV 스냅샷 (NaN 없음, int64)
- `DataReader('KS11'/'KQ11')`: 지수 일봉 정상 (네이버 소스)

## 저장 전략

- **분봉 원본**: 일자별 parquet 1파일(전 종목 통합, zstd, `minute-YYYY-MM-DD.parquet`)
  → GitHub Release 자산(태그 `minute-YYYY-MM`). Turso에 넣지 않는 이유:
  일 105만 행 = 월 2,300만 행으로 무료 쓰기 한도(월 1,000만 행) 초과.
- **Turso krx_market**: 일봉·수급·지수(전 종목, 일 수천 행)와
  `minute_prices` 롤링 캐시(조회 종목 최근 5거래일)만.

## 일일 배치 흐름 (collector/daily.py, 평일 16:30 KST)

1. 휴장 판정: 005930 분봉 + FDR KS11 교차 확인
   (분봉 없음 + KS11 있음 = 업스트림 이상/제공범위 밖으로 구분)
2. Turso 적재 (분봉보다 먼저 — 소스 무관하므로 분봉 실패에 연좌 방지):
   stocks upsert + 미등재 비활성화 → daily_prices(pykrx→FDR 폴백, KONEX 제외)
   → 수급(pykrx, 실패 시 스킵) → 지수(FDR) → 분봉 캐시 정리
3. 분봉 수집(전 종목, 0.5초 간격 ≈ 23분, 연속 20회 실패 시 중단)
   → parquet → Release 업로드(기존 자산보다 5%+ 작으면 결손 의심으로 거부)

## 프로바이더 교체 계획

- v0: NaverProvider (현재)
- v1: KiwoomRestProvider — 서버점검 종료 후. 스텁: collector/providers/kiwoom.py.
  토큰 IP 제약 때문에 주문·수집 모두 Actions 같은 런에서 처리해야 함.
