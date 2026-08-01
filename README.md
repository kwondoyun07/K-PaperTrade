# K-PaperTrade

실제 KRX 1분봉 데이터로 돌아가는 국내주식 모의투자(페이퍼 트레이딩) 웹.

> **모의투자·교육용**입니다. 실계좌·실거래 연동은 하지 않으며, 종목 추천·투자 권유가 아닙니다.

## 스택

- 웹: Next.js (App Router, TypeScript) → Vercel Hobby
- DB: Turso Free (libSQL) × 2 — `krx-market`(시세) / `trading`(계좌·주문·판단)
- 수집·배치: `/collector` Python(uv) + GitHub Actions cron
- 분봉 원본: 일자별 parquet → GitHub Release 자산 (Turso `minute_prices`는 최근 5거래일 롤링 캐시만)

## 요구사항

- Node.js 20+, pnpm
- Python 3.11+, uv
- [Turso CLI](https://docs.turso.tech/cli/introduction)

## 설정

1. Turso DB 2개 생성 + 토큰 발급:

   ```sh
   turso db create krx-market
   turso db create trading
   turso db show --url krx-market      # → TURSO_KRX_MARKET_URL
   turso db tokens create krx-market   # → TURSO_KRX_MARKET_AUTH_TOKEN
   # trading도 동일하게
   ```

2. 스키마 적용 (별도 마이그레이션 러너 없음 — sql 파일을 직접 적용):

   ```sh
   turso db shell krx-market < db/migrations/krx_market/001_init.sql
   turso db shell trading < db/migrations/trading/001_init.sql
   ```

3. 환경변수: `.env.example`을 `.env`로 복사해 값 채우기.
   `TURSO_*` 토큰은 서버 전용 — `NEXT_PUBLIC_` 접두사 금지.

## 실행

```sh
pnpm install
pnpm dev        # http://localhost:3000
pnpm test       # 체결 엔진 vitest
```

상세 문서는 [docs/](docs/) 참고 — [데이터 파이프라인](docs/data-pipeline.md) · [체결 엔진](docs/engine.md)

## 수집기 (collector)

```sh
cd collector
uv sync                                   # Python 3.12 고정 (.python-version)

# 백필 — 네이버가 제공하는 최근 ~6거래일 분봉 전부 → data/minute/*.parquet
uv run python backfill.py                 # 전 종목 (~2,700요청, 기본 0.5초 간격 ≈ 25분)
uv run python backfill.py --tickers 005930,000660
uv run python backfill.py --upload        # GitHub Release 업로드까지 (gh CLI 필요)

# 일일 배치 — Actions가 평일 16:30 KST에 실행하는 것과 동일 진입점
uv run --env-file ../.env python daily.py
uv run python daily.py --tickers 005930 --skip-upload   # 스모크

# 파서 테스트
uv run python test_parse.py
```

- 분봉 원본은 Turso가 아니라 **일자별 parquet(zstd) → GitHub Release**(태그
  `minute-YYYY-MM`)에 보관한다. Turso 무료 쓰기 한도(월 1,000만 행) 보호 목적.
- 네이버 분봉은 **최근 ~6거래일만** 제공되므로(2026-08-01 실측) 일일 적재가
  누락되면 그 날짜 분봉은 복구 불가. Actions cron이 핵심이다.
- GitHub Actions 시크릿 필요: `TURSO_KRX_MARKET_URL`, `TURSO_KRX_MARKET_AUTH_TOKEN`.
- pykrx(KRX 포털) 벌크 API가 불안정할 때: 일봉은 FDR 스냅샷 폴백(당일만),
  지수는 FDR(KS11/KQ11) 단독, 수급은 실패 시 스킵(보조 데이터).

## 데이터 출처 고지

- v0 분봉 데이터는 네이버 금융의 **비공식** 엔드포인트를 사용합니다.
  개인 연구용 저빈도 호출(초당 1회 이하, 지수 백오프 재시도)만 수행합니다.
- 키움증권 REST API 서버점검 종료 후 `KiwoomRestProvider`로 교체 예정입니다.

## 브랜치 전략

- `main`(master 역할) · `develop` — 상시 브랜치
- 기능 개발: `develop`에서 `feature/*` 분기 → 완료 시 `develop`에 머지
- 릴리스: `develop` → `main` PR로만 반영 (GitHub 원격 연결 후)

## 진행 상황

- [x] 1단계: 스캐폴딩(루트 Next.js + `/collector`) + Turso 스키마 + `.env.example`
      + 디자인 시안(`K-PaperTrade.dc.html`) TS 포팅 — 현재 화면은 **더미 데이터**
- [x] 2단계: NaverProvider(진짜 분봉 OHLC) + 전 종목 백필 + parquet/Release + 일봉·수급·지수 수집 (GitHub Actions)
- [x] 3단계: 체결 엔진(`lib/engine/`, 순수 함수) + vitest 18케이스 — [docs/engine.md](docs/engine.md)
- [ ] 4단계: API Routes + 리플레이 세션 (서버측 커서 컷)
- [ ] 5단계: 화면 실데이터 연결 + 장중 폴링
- [ ] 6단계: 성과 지표 + ai_decisions 수익률 배치

v1 범위 밖(미구현): VI(변동성완화장치), 동시호가, 공매도, 실거래 연동.
