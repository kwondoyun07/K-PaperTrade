# 백업 데이터 소스 · 백테스트 라이브러리 조사

조사일 2026-08-16. 모든 수치는 실제 HTTP 호출·DB 대조 결과다.

---

## 1. 한국주식데이터 (aikstockdata.com)

awesome-quant에 "Korea Stock Data"로 올라온 것. 레포는
[na77tech-creator/aikstockdata](https://github.com/na77tech-creator/aikstockdata),
데이터는 `https://aikstockdata.com/data/public/` 아래 정적 JSON이다.

### 실측 확인

```
$ curl -sI https://aikstockdata.com/data/public/today.json
HTTP/1.1 200 OK
Access-Control-Allow-Origin: *
Cache-Control: public, max-age=0, must-revalidate
Server: cloudflare
```

- **가입·API키 정말 없다.** 인증 헤더 없이 200. CORS 개방(`*`), Cloudflare 캐시 HIT, 응답 0.25초.
- 원천은 **금융위원회 공공데이터포털(시세) + 금감원 DART(공시)**. 자체 수집이 아니라 공공데이터 가공물이다.
- 라이선스: 출처 표기 시 영리 포함 자유 이용. 표기 문구는 `kstockdata.CITATION`에 박아 뒀다.
- 없는 종목은 깔끔하게 404 (`s/999999.json` → 404).

### 엔드포인트

| 경로 | 내용 | 크기 |
| --- | --- | --- |
| `today.json` | KOSPI/KOSDAQ 지수 OHLC, 등락 종목수, 주요 공시 요약 | 7KB |
| `quotes.json` | 1,462종목 **전 필드 OHLCV** (단일 거래일) | 400KB |
| `s/{code}.json` | 종목 1건 — 시세 + DART 재무 + 최근 공시 | 5KB |
| `s/{code}_history.json` | **250거래일 `[date, close, volume]`** | 7KB |
| `disclosure_impact.json` | 공시 유형별 시장조정 초과수익 + 건별 lookup | 770KB |
| `disclosures.json` / `disclosures_intraday.json` | 최근 7일 공시 / 당일 공시(접수시각 포함) | 380KB / 60KB |
| `rankings.json` | 자체 산출 성장·성과 랭킹 | 17KB |

MCP 서버도 있다: `https://mcp.aikstockdata.com/mcp` (12 tools).

### 정확도 — 우리 DB와 전 종목 대조

2026-08-13 기준, `quotes.json` 1,462종목 전부를 우리 `daily_prices`와 맞대 봤다.

```
overlap=1462 OHLC_mismatch=0 volume_mismatch=641
aik/ours volume ratio: min=1.0000 p50=1.0017 max=1.2434 always>=1? True
history overlap days: 59 close exact: 59 vol exact: 8
```

- **시가·고가·저가·종가는 1,462종목 전부 완전 일치.** 오차 0건. 신뢰할 만하다.
- **거래량은 항상 우리보다 크거나 같다** (중앙값 +0.17%, 최대 +24%). 랜덤 오차가 아니라
  한쪽 방향이므로 시간외 거래 포함 차이로 보인다. 거래량비(vol/MA20) 지표에 섞어 쓰면
  기준이 흔들리니 **거래량은 한 소스로만 계산해야 한다.**
- 250일 히스토리 종가도 59/59 일치 (005930, 최근 60일 대조).

### 치명적 한계 — 시세는 T+1이다

발행처가 명시한다: `"전 영업일(T+1) 확정 종가 — 실시간 아님"`.

```
today.json  quote_as_of=20260813  disclosure_through=20260814  generated=2026-08-14 18:28
our latest daily_prices date: 2026-08-14
```

**2026-08-16(일) 시점에 공개된 마지막 시세가 08-13인데, 우리 DB에는 이미 08-14가 있었다.**
거래일 D 저녁에 발행되는 건 D-1 종가다. 주말이면 최대 3일까지 벌어진다.

→ **pykrx/FDR 폴백으로는 못 쓴다.** 폴백은 수집이 실패한 그날 밤 그 날짜를 대신 채워야
하는데, 이 소스에는 애초에 그 날짜가 없다. "무료 백업 시세 소스"라는 기대는 여기서 깨진다.

### 나머지 한계

- **유니버스 1,500 (실수집 1,462).** 우리 `stocks`는 2,763종목. 시총 하위 ~1,300종목이 없다.
  우리 watchlist(시총 상위 50)도 **48/50만 커버** — 빠진 건 `005935 삼성전자우`(우선주),
  `138040 메리츠금융지주`. 둘 다 `s/{code}.json` 404. **우선주가 통째로 빠진다.**
- **히스토리에 OHLC가 없다.** `[date, close, volume]` 3열뿐. `daily_prices`는 open/high/low가
  NOT NULL이라 과거 구간을 이 소스로 채울 수 없다. (OHLC가 있는 `quotes.json`은 단 하루치다.)
- 거래정지·정리매매 종목은 시가·고저·거래량이 0으로 온다(발행처 명시 결측규칙). 그대로 적재하면
  시가 0원이 들어간다 — 파서에서 버린다.
- 상장폐지 종목은 유니버스에서 사라진다 → **이 데이터로 만든 백테스트에는 생존편향이 있다.**

### 그래서 쓸 수 있는 자리

`collector/kstockdata.py` 구현. 배선은 하지 않았다(daily.py·decide.py는 남의 파일).

| 함수 | 용도 | 판단 |
| --- | --- | --- |
| `parse_quotes` | 단일 거래일 OHLCV → `daily_prices` 스키마 그대로 | 폴백 ✗ / **파이프라인 감사 ○** — OHLC 0건 불일치라 우리 수집 버그를 공짜로 잡아낸다 |
| `parse_history` | 250거래일 종가·거래량 | **백테스트용 ○** (아래) / `daily_prices` 적재 ✗ (OHLC 없음) |
| `parse_priors` | 공시 유형별 초과수익 | **decide.py 프롬프트 재료 ○** |

**히스토리가 진짜 메우는 구멍**: 우리 `daily_prices`는 watchlist 50종목만 253일이고,
나머지 2,700여 종목은 2026-07-24부터 **17거래일뿐**이다.

```
rows per date: ... 2026-07-23: 50, 2026-07-24: 2646, ... 2026-08-14: 2763
005930: 253일 (2025-08-01~)
```

즉 시총 상위 50 밖으로 백테스트 유니버스를 넓히는 순간 데이터가 없다. 여기서 1,462종목 ×
250일 종가를 무료·무키로 받을 수 있다(약 1,462 요청 / 10MB). 일봉 모멘텀·이동평균·
횡단면 랭킹은 종가만으로 계산되므로 백테스트 목적에는 충분하다. **단 생존편향은 남는다.**

### 공시 초과수익 (`disclosure_impact.json`) — 이게 제일 값어치 있다

공시 접수일 다음 거래일 종가 기준 1·5·20거래일 초과수익(시장 등락률 차감) 중앙값을
유형별로 낸다. 접수시각(HH:MM)까지 붙여 장전/장중/장후를 나눈다 — 발행처 말로는
DART 최근공시 목록에만 남아 있는 값이라 다른 데서 재현 못 한다. 우리가 직접 만들려면
전 종목 이벤트 스터디를 돌려야 하는 값이다.

`uv run python test_kstockdata.py --live` 실측 (2026-08-14 스냅샷, h5):

```
자사주 신탁계약 체결      h5 excess= +6.33% up= 80.8% n=  26 sig=True
공급계약 체결            h5 excess= +1.16% up= 55.1% n= 167 sig=False
잠정 실적(연결)          h5 excess= +1.15% up= 56.0% n= 184 sig=False
최대주주 변경            h5 excess= +0.77% up= 62.1% n=  29 sig=False
배당 결정               h5 excess= +0.47% up= 54.5% n=  66 sig=False
정기 실적 보고서          h5 excess= -2.85% up= 39.1% n=  23 sig=False
잠정 실적(별도)          h5 excess= -3.63% up= 32.8% n= 122 sig=True
전환사채(CB) 발행        h5 excess= -4.46% up= 35.0% n=  20 sig=False
```

**우리한테 직접 쓸모 있는 사실 두 가지:**

1. `잠정 실적(별도)`는 5일 뒤 **-3.63%**, 상승 비율 32.8%, 신뢰구간이 0을 안 넘는다.
   "실적 발표 = 호재"라고 읽으면 손해다. decide.py가 지금 공시 제목만 보고 판단하는데,
   실적 공시를 호재로 읽는 편향이 있다면 **BUY < HOLD 문제의 한 조각일 수 있다.**
2. 8개 유형 중 6개가 신뢰구간에 0을 포함한다. **공시 유형 자체로는 알파가 없다.**
   프롬프트에 넣을 때 이 사실까지 같이 넣어야 AI가 공시를 과대평가하지 않는다.

주의: 표본 창이 짧다(2026-07-20~08-12, 1,216건). h20은 아직 미발행. 유형별 n이 20~250이라
`자사주 신탁계약 체결`(n=26, +6.33%) 같은 건 과적합 위험이 크다.

### 결론

**"pykrx/FDR 대체 시세 폴백"으로는 못 쓴다 — T+1 지연 + 유니버스 1,500 + 우선주 누락 +
히스토리 OHLC 없음.** 억지로 배선하면 폴백이 필요한 순간에 정확히 실패한다.

**쓴다면 세 자리:** (a) 250일 종가로 백테스트 유니버스 확장,
(b) 공시 유형 초과수익을 decide.py 프롬프트 재료로, (c) 우리 OHLC 수집 감사.
(b)가 가장 값이 크다. 배선은 사람이 판단할 것.

---

## 2. 백테스트 라이브러리

우리 조건: 한국주식 일봉(+1분봉), 데이터는 Turso, 파이썬, 별도 레포 K-Quant 예정.
전략 모양은 **횡단면**이다 — "50종목 중 어떤 걸 살까"지 "이 한 종목을 언제 살까"가 아니다.

### 유지보수 상태 (PyPI 마지막 업로드 · GitHub 마지막 push, 2026-08-16 실측)

| 라이브러리 | 최신 | PyPI 최종 | GitHub push | ★ | 라이선스 |
| --- | --- | --- | --- | --- | --- |
| vectorbt | 1.1.0 | 2026-07-05 | 2026-08-02 | 8.7k | **Apache 2.0 + Commons Clause** |
| bt | 1.2.0 | 2026-04-25 | 2026-08-07 | 3.0k | MIT |
| backtesting.py | 0.6.6 | 2026-07-22 | 2026-08-05 | 8.9k | **AGPL-3.0** |
| quantstats | 0.0.81 | 2026-01-13 | 2026-07-20 | 7.6k | Apache-2.0 |
| zipline-reloaded | 3.1.1 | 2025-07-19 | 2026-01-06 | 1.9k | Apache-2.0 |
| qlib | — | — | 2026-07-23 | 47.5k | MIT |
| backtrader | 1.9.78.123 | **2023-04-19** | **2024-08-19** | 22.9k | GPL-3.0 |
| pyfolio-reloaded | 0.9.9 | 2025-06-02 | — | — | Apache-2.0 |
| PyPortfolioOpt | 1.6.0 | 2026-02-26 | — | — | MIT |
| empyrical | 0.5.5 | **2020-10-13** | — | — | Apache-2.0 |
| zipline (원본) | 1.4.1 | **2020-10-05** | — | — | Apache-2.0 |

한국 시장 캘린더는 `exchange_calendars`(v4.13.2, 2026-03)에 **XKRX가 있다**
(`exchange_calendar_xkrx.py`, `xkrx_holidays.py`) — zipline-reloaded·bt 계열 모두 붙일 수 있다.

### 평가

- **backtrader** — 별 22.9k로 제일 유명하지만 **3년 넘게 릴리스 없음**(2023-04). 이벤트
  드리븐이라 파라미터 스윕이 느리고, 횡단면 랭킹을 짜려면 보일러플레이트가 길다. 탈락.
- **zipline (원본)** — 2020년 사망. **zipline-reloaded**가 후계지만 데이터를 bundle로
  ingest해야 하고 US 중심 전제가 많다. Turso에서 DataFrame 뽑아 쓰는 우리한테는
  ingest 의식 자체가 순비용. 탈락.
- **backtesting.py** — 활발하고 API가 제일 쉽지만 **단일 종목 전용**이다. 우리 문제(50종목 중
  선택)를 표현할 수 없다. 게다가 **AGPL-3.0** — 나중에 웹으로 뭔가 서비스하면 소스 공개 의무가
  걸린다. 우리 웹앱이 이미 있으니 위험. 탈락.
- **qlib** (Microsoft, 47.5k) — ML 기반 퀀트 플랫폼. 데이터 핸들러·모델·백테스트가 한 덩어리라
  가장 강력하지만 학습곡선이 제일 가파르고 자체 데이터 포맷을 강요한다. K-Quant 초기엔 과하다.
- **vectorbt** — numba 벡터화로 파라미터 스윕이 압도적으로 빠르고, 활발히 릴리스된다(1.1.0).
  다만 (a) **Commons Clause** — "소프트웨어 기능에 가치가 실질적으로 의존하는 유료 서비스"
  제공 금지. 개인 매매엔 무관하지만 나중에 유료화하면 걸린다. (b) 최근 0.28 → 1.x 메이저
  점프라 API 변동 위험. (c) 배열 사고방식 강제라 학습곡선이 있다.
- **bt** — pandas 네이티브, MIT, 활발(2026-08 push). `SelectTop` → `WeighEqually` →
  `Rebalance` 같은 Algo 스택이 **우리 전략 모양 그대로다.** API가 작아서 하루면 익힌다.
  단점은 바 단위 파이썬 루프라 느리다는 것.
- **quantstats / pyfolio-reloaded** — 백테스터가 아니라 성과 리포트. 어느 엔진에도 붙는다.
  pyfolio-reloaded는 1년 넘게 조용하니 **quantstats** 쪽.
- **empyrical** — 2020년 이후 죽었다. 쓰지 마라. 지표는 quantstats에 다 있다.
- **PyPortfolioOpt** — 백테스터가 아니라 비중 최적화기. 필요해지면 그때.

### 추천: **bt** (+ 리포트는 quantstats)

근거:

1. **속도가 우리 병목이 아니다.** 250거래일 × 최대 1,462종목이 전부다. vectorbt의 numba
   벡터화는 이 규모에서 이득이 없다 — 있지도 않은 문제를 위해 학습곡선과 Commons Clause를
   같이 사는 셈이다.
2. **전략 모양이 맞는다.** bt의 Algo 스택이 "신호로 랭킹 → 상위 N 선택 → 균등 비중 →
   리밸런스"를 그대로 표현한다. 지금 decide.py가 하는 일이 정확히 이거다.
3. **MIT.** vectorbt(Commons Clause)·backtesting.py(AGPL)와 달리 나중에 뭘 해도 안 걸린다.
4. **pandas 네이티브.** Turso `query()` → DataFrame → `bt.Backtest`. bundle ingest 없음.
5. 유지보수 살아 있다(2026-08-07 push, PyPI 2026-04).

**업그레이드 경로:** 파라미터 스윕이 분 단위로 늘어나면 그때 vectorbt로 옮겨라.
그 전엔 필요 없다.

**그리고 지금 당장 필요한 건 백테스트 라이브러리가 아니다.** "BUY가 HOLD보다 못 올랐다"는
현재 최우선 문제는 전략 백테스트가 아니라 `ai_decisions` 테이블의 이벤트 스터디다 —
`action` 별 `ret_d5` group-by. SQL 한 줄이면 끝나고 이미 데이터가 있다.
bt는 **규칙 기반 대안 전략을 AI와 비교할 때**부터 필요하다.

---

## 부록: `collector/kstockdata.py`

```
$ uv run python test_kstockdata.py --live
파서 OK
live quotes: 1428행, date=2026-08-13, 예: {'ticker': '000020', 'date': '2026-08-13',
  'open': 5310, 'high': 5310, 'low': 5130, 'close': 5140, 'volume': 122645}
live history 005930: 250행 2025-08-05~2026-08-13
live priors: 8유형, 유의(CI가 0 미포함): ['잠정 실적(별도)', '자사주 신탁계약 체결']
라이브 OK — 자료: 한국주식데이터(aikstockdata.com) — 원천: 금융감독원 DART · 금융위원회 공공데이터포털
```

1,462 → 1,428행은 거래정지 34종목(시가 0)을 파서가 버린 결과다.
`parse_quotes`가 내는 dict는 `daily_prices` 컬럼과 1:1이라 그대로 upsert에 넣을 수 있다.
어디에도 배선하지 않았다 — daily.py·decide.py는 사람이 판단할 것.
