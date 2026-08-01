# API (4단계)

`/api/v1`, zod 검증, 전부 서버 라우트(Turso 접근은 서버 전용).
인증: `APP_PASSWORD` 설정 시 middleware가 전 경로 보호(쿠키 세션, `/login`).
미설정이면 로컬 개발 모드로 인증 생략. 다중 사용자 전환 시 Auth.js로 교체(훅: middleware.ts).

## 엔드포인트

| 메서드·경로 | 설명 |
|---|---|
| `GET /stocks/search?q=` | 종목 검색 (is_active=1, 이름·티커 LIKE, 20건) |
| `GET /stocks/:ticker/minutes?date=&until=&session=` | 분봉. **session 지정 시 서버가 DB의 세션 커서로 컷** — 클라이언트 until 무시 |
| `GET /stocks/:ticker/daily?from=&to=` | 일봉 (기본 최근 120) |
| `GET /stocks/:ticker/flows?limit=` | 투자자별 순매수 |
| `GET /quotes?tickers=` | 장중 폴링 프록시(최대 10종목): 네이버 분봉 → 캐시 upsert → 라이브 PENDING 정산 → 현재가 |
| `POST/GET /accounts` | 계좌 생성·목록 |
| `GET /accounts/:id/portfolio` | 현금+보유 평가 |
| `GET /accounts/:id/performance` | 스냅샷+지수 (MDD·샤프는 6단계) |
| `POST/GET /orders` | 라이브 주문 접수·조회 (`?account_id=`) |
| `POST/GET /replay/sessions` | 리플레이 세션 생성(분봉 존재 검증)·목록 |
| `POST /replay/:id/tick` | 커서 전진 `{minutes, finish}` → PENDING 정산, finish 시 result_json 저장 |
| `POST /replay/:id/orders` | 리플레이 주문 — ordered_at은 **서버 커서**(가상 시각) |
| `POST/GET /ai-decisions` | AI 판단 기록·조회 |
| `POST /auth/login` | 비밀번호 → 쿠키 세션 |

## 룩어헤드 차단 (서버 강제)

1. 커서는 `replay_sessions.cursor_ts`(DB)에만 존재 — tick으로만 전진
2. 분봉 조회: `session` 파라미터면 서버가 커서로 컷(클라이언트 until 무시)
3. 주문 ordered_at = 서버 커서. 정산은 tick에서 `cutBars(bars, cursor)` 후
   `settlePending`(접수 시각 이후 봉만) — 이중 방어
4. 엔진 시그니처 자체가 분봉 1개 단위 판정 (docs/engine.md)

검증: `lib/engine/settle.test.ts` + 스모크(위조 until 요청이 커서로 고정되는 것 확인).

## 데이터 소스 체인

- 분봉: 로컬 parquet(`collector/data/minute`, 개발) → GitHub Release(`GITHUB_REPO` env, 배포) → Turso 롤링 캐시
- 전일 종가(가격제한폭 기준): daily_prices → 직전 일자 parquet 마지막 종가 폴백
- DB 클라이언트: TURSO env 미설정 시 `file:.data/*.db` 폴백 (`pnpm migrate`로 스키마 적용)

## 주문 생명주기

접수(`placeOrder`) 시 즉시 검증: 호가단위·가격제한폭(지정가), 잔고부족(매도), 현금부족(매수 추정)
→ 통과 시 PENDING 저장 → 정산(`settleOwnerOrders`): 리플레이는 tick, 라이브는 quotes 폴링이 트리거
→ FILLED(executions 기록 + positions·cash 갱신, batch 트랜잭션) 또는 REJECTED(사유 기록).
