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
```

수집기 (스크립트는 2단계에서 추가):

```sh
cd collector
uv sync
```

## 데이터 출처 고지

- v0 분봉 데이터는 네이버 금융의 **비공식** 엔드포인트를 사용합니다.
  개인 연구용 저빈도 호출(초당 1회 이하, 지수 백오프 재시도)만 수행합니다.
- 키움증권 REST API 서버점검 종료 후 `KiwoomRestProvider`로 교체 예정입니다.

## 진행 상황

- [x] 1단계: 스캐폴딩(루트 Next.js + `/collector`) + Turso 스키마 + `.env.example`
      + 디자인 시안(`K-PaperTrade.dc.html`) TS 포팅 — 현재 화면은 **더미 데이터**
- [ ] 2단계: NaverMinuteProvider + 전 종목 백필 + parquet/Release 업로드 + 일봉·수급 수집 (GitHub Actions)
- [ ] 3단계: 체결 엔진 + vitest (상·하한가 거부, 수수료·거래세, 호가단위, 다음 분봉 체결, 룩어헤드 차단)
- [ ] 4단계: API Routes + 리플레이 세션 (서버측 커서 컷)
- [ ] 5단계: 화면 실데이터 연결 + 장중 폴링
- [ ] 6단계: 성과 지표 + ai_decisions 수익률 배치

v1 범위 밖(미구현): VI(변동성완화장치), 동시호가, 공매도, 실거래 연동.
