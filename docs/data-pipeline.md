# 데이터 파이프라인

## 소스 실측 결과

### 키움 REST API (현재 주력, 모의투자) — 2026-08-02 실측

`POST https://mockapi.kiwoom.com/api/dostk/chart`, 헤더 `api-id: ka10080`

- 토큰: `POST /oauth2/token {grant_type, appkey, secretkey}` → `{token, expires_dt}` (약 24시간)
- 바디: `{stk_cd, tic_scope: "1", upd_stkpc_tp: "1"}`
- 응답 배열 `stk_min_pole_chart_qry`, **최신순 900건/페이지**
  (`cntr_tm` YYYYMMDDHHMMSS, `open_pric`/`high_pric`/`low_pric`/`cur_prc`, `trde_qty` 분당 거래량)
- **가격에 +/- 부호가 붙어 온다** — 전일 대비 방향 표시일 뿐이므로 제거해야 한다
- 연속조회: 응답 헤더 `cont-yn=Y` + `next-key`를 다음 요청 헤더로.
  **45페이지(40,500건, 5개월+)까지 확인했고 그 시점에도 `cont-yn=Y`** — 사실상 제한이 안 보인다
- **호출 제한: API ID당 초당 1회**(초과 시 HTTP 429 / 1700). 1.1초 간격 사용
- 실전 호스트(`api.kiwoom.com`)에 모의 키를 쓰면 8030으로 거부 — 실거래 오용이 자동 차단된다

**네이버와 대조(2026-07-31, 3종목 1,138봉): OHLC 전부 일치.**
시가·종가 단일가 봉의 거래량만 미세 차이(스냅샷 시점 차이로 추정).

교체 이유: 네이버는 ~6거래일뿐이라 "하루라도 놓치면 영구 유실"이었는데,
키움은 과거 백필이 가능해 그 위험이 사라진다. 공식 API이기도 하다.
실측: 1종목 6/1 이후 43거래일 16,213행 수집에 22초.

### 네이버 분봉 API (폴백, 비공식) — 2026-08-01 실측

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

- 벌크 API 3종(전 종목 일봉 by ticker, 투자자별 수급, 지수)이 **주말 내내 빈 응답**
  (2026-08-01~02 실측, 로컬·GitHub Actions 양쪽에서 동일). 평일 재확인 필요
- 종목당 일봉(`get_market_ohlcv_by_date`)은 정상
- `pkg_resources` 의존 → `setuptools<81` 고정 필요
- 이 불안정성 때문에 일봉은 3단 폴백(아래)을 둔다

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
   stocks upsert + 미등재 비활성화 → daily_prices → 수급(pykrx, 실패 시 스킵)
   → 지수(FDR) → 분봉 캐시 정리
3. 분봉 수집(전 종목, 0.5초 간격 ≈ 23분, 연속 20회 실패 시 중단)
   → parquet → Release 업로드(기존 자산보다 5%+ 작으면 결손 의심으로 거부)
4. **일봉 최후 폴백** — 2)에서 0행이었으면 3)에서 수집한 parquet로 파생 후 적재
5. 계좌 스냅샷 + ai_decisions 수익률 배치 (trading DB)

### 일봉 3단 폴백

| 순서 | 소스 | 조건 |
|---|---|---|
| 1 | pykrx 벌크 (`get_market_ohlcv`) | 정상일 때 |
| 2 | FDR KRX 스냅샷 | 당일 실행일 때만 (스냅샷은 최근 거래일 값) |
| 3 | 당일 분봉 parquet 파생 | 위 둘 다 실패. 거래량이 장중 합계라 공식 일봉과 미세 차이 |

3단까지 모두 실패하면 exit 1로 실패 처리한다 — 조용히 넘어가면 가격제한폭
기준·포트폴리오 평가·AI 수익률이 전부 빈 채로 남는다.

## 저장소·배포 설정 (2026-08-02 기준)

- GitHub: `kwondoyun07/K-PaperTrade` — **비공개**. 공개 전환은
  `gh repo edit --visibility public` 한 줄(되돌리기 불가하므로 신중히).
- 비공개일 때 영향:
  - Actions 무료 2,000분/월 (일 배치 ~30분 × 21영업일 ≈ 630분 — 여유)
  - Release 자산을 공개 URL로 못 받음 → 서버가 API로 인증 다운로드
    (`GITHUB_RELEASE_TOKEN`, contents:read). 공개로 바꾸면 토큰 없이 동작.
- Actions 시크릿: `TURSO_KRX_MARKET_URL/AUTH_TOKEN`,
  `TURSO_TRADING_URL/AUTH_TOKEN`(스냅샷·AI 배치), `TURSO_API_TOKEN`(주간 덤프).

### 운영 주의

- **cron 60일 자동 비활성화**: 저장소에 60일간 커밋이 없으면 GitHub가
  스케줄 워크플로를 끈다. 분봉은 소급 수집이 불가하므로(제공창 ~6거래일)
  장기 방치 시 데이터가 끊긴다 — 주간 백업 워크플로가 매주 커밋을 남기므로
  실질적으로 방지되지만, 백업이 실패하면 이 안전장치도 사라진다.
- 잡 실패 시 GitHub가 저장소 소유자에게 메일을 보낸다(기본 알림). 실패를
  놓치면 그날 분봉은 6거래일 뒤 영구 유실 — `workflow_dispatch`로 날짜를
  지정해 재실행할 수 있는 것도 그 창 안에서만 의미가 있다.

## 프로바이더 선택

`collector/providers/make_provider()`가 결정한다:
- `KIWOOM_APP_KEY`/`SECRET`이 있으면 **키움**(기본)
- 없으면 **네이버**로 폴백(경고 로그). 이 경우 과거 백필은 불가
- `--provider` 인자나 `PROVIDER` env로 강제 지정 가능

```sh
uv run --env-file ../.env python backfill.py --tickers 005930 --since 2026-06-01
uv run --env-file ../.env python daily.py --date 2026-07-31
```

전 종목 일일 수집 소요: 네이버 약 23분(0.5초 간격) / 키움 약 51분(1.1초 간격).
둘 다 Actions 잡 한도(6시간) 안이다.
