# 브로커 어댑터 · 키움 모의계좌 미러링 (v1.5)

자체 체결 엔진이 가상 계좌에서 체결한 주문을 키움 **모의투자** 계좌에도 내보내,
실거래 경로를 가짜 돈으로 검증한다.

## 구조

```
(lib/broker/ 없음)         BrokerAdapter 인터페이스는 호출부가 생길 때 만든다 — 아래 참고
collector/kiwoom_order.py  키움 모의 주문 클라이언트 + 미러링 배치
.github/workflows/mirror.yml  Actions 실행 (concurrency group: kiwoom)
```

**키움 구현체가 TS 쪽에 없는 이유**: 키움 토큰은 IP 화이트리스트에 묶여 있어
Vercel 서버리스(유동 IP)에서 주문이 나갈 수 없다. 토큰 발급→주문을 Actions 런
하나 안에서 끝낸다. 서버 코드에 실주문 경로가 아예 없는 것 자체가 안전장치다.

`paperBroker`는 기존 함수(`placeOrder` / `getPositions` / `getPortfolio` /
`latestClose`)를 그대로 위임한다. `cancelOrder`만 새로 추가했고 PENDING 주문만
CANCELLED로 바꾼다(체결·거부된 주문을 되돌리면 잔고가 어긋난다).

## 키움 주문 API (openapi.kiwoom.com API 가이드, 2026-08-02 확인)

| 항목 | 값 |
|---|---|
| 호스트 | `https://mockapi.kiwoom.com` (모의 전용. 실전 호스트 문자열은 코드에 없음) |
| 주문 경로 | `POST /api/dostk/ordr` |
| api-id | `kt10000` 매수 / `kt10001` 매도 / `kt10002` 정정 / `kt10003` 취소 |
| 요청 body | `dmst_stex_tp`, `stk_cd`, `ord_qty`, `ord_uv`, `trde_tp` |
| `dmst_stex_tp` | `KRX` / `NXT` / `SOR` — **모의투자는 NXT 미지원이라 KRX 고정** |
| `trde_tp` | `0` 보통(지정가) / `3` 시장가 / `5` 조건부지정가 / `6` 최유리 / `7` 최우선 / `10` 보통IOC / `13` 시장가IOC / `61` 장전시간외 / `62` 시간외단일가 / `81` 장후시간외 |
| 응답 | `ord_no`(주문번호), `dmst_stex_tp`, `return_code`, `return_msg` |
| 계좌 경로 | `POST /api/dostk/acnt` — `ka00001` 계좌번호조회 / `kt00001` 예수금상세현황 / `kt00018` 계좌평가잔고내역 |
| 유량 제한 | API ID당 초당 1회 (1.1초 간격 유지) |

**계좌번호**: 주문 body에 계좌번호 필드가 없다. 앱키가 계좌에 묶여 있고,
계좌번호가 필요하면 `ka00001`로 조회한다 — `uv run python kiwoom_order.py --accounts`.

## 미러링 규칙

대상: `orders`에서 `owner_type='ACCOUNT'` AND `owner_id = --account-id` AND
`status='FILLED'` AND `broker_order_id`가 비어 있고 `ordered_at >= since`(기본 오늘 KST).

- **`--account-id` 필수**: 없으면 모든 계좌의 체결이 한 키움 계좌로 합쳐 나간다. 미지정이면 즉시 종료(exit 2).
- **전송 전 선점**: 보내기 **전에** `broker_order_id`를 `SENDING:<run>`으로 잡는다
  (`... WHERE id=? AND COALESCE(broker_order_id,'')='' RETURNING id`, 빈 결과면 skip).
  전송 후 기록이면 타임아웃·5xx로 응답만 유실됐을 때 키움엔 주문이 들어갔는데 기록이 없어
  다음 런이 같은 주문을 또 낸다. `Turso.execute`는 rowsAffected를 주지 않아 `RETURNING`으로 확인한다.
- **전송 결과 마킹**: 성공은 실제 `ord_no`로, 실패는 `FAILED:<사유>`로 덮어쓴다(선점 표식을 쥔 행만).
  **자동 재전송하지 않는다** — 중복 주문이 미전송보다 위험하다. `FAILED:`는 사람이 키움 화면과 대사한다.
- **건별 격리**: 상한·형식 위반(`LimitError`)은 그 행만 `SKIP:<사유>`로 마킹하고 넘어간다.
  중단시키면 같은 행에서 매번 멈춰 뒤 주문이 전부 막힌다.
- **`--since`**: 형식(`YYYY-MM-DD`) + 미래 금지 + 과거 7일 이내로 검증한다. 컬럼이 새로 생기면
  과거 체결이 전부 NULL이라 히스토리 전체가 한 번에 나갈 수 있다.
- **상한**: 수량 1,000주 / 건당 1,000만원 / 런당 20건(`max(1, min(--limit, 20))` — 하한이 없으면
  `--limit -1`이 SQLite에서 무제한이 된다).
- 주문 유형은 원 주문 그대로 미러링한다(MARKET→`trde_tp=3`, LIMIT→`trde_tp=0` + `ord_uv`).
  체결가는 금액 상한 검증에만 쓴다.

`broker_order_id` 값으로 상태를 읽는다: 비어 있음=미전송, `SENDING:<run>`=전송 중(또는 런이
중간에 죽음 — 사람 확인), `FAILED:<사유>`=전송 실패, `SKIP:<사유>`=검증 탈락, 그 외=키움 주문번호.

`orders.broker_order_id`는 마이그레이션이 아니라 배치 시작 시
`ALTER TABLE ... ADD COLUMN`으로 보장한다 — `scripts/migrate.mjs`가 마이그레이션
파일을 매번 전부 재실행하므로 비멱등한 ALTER를 거기 둘 수 없다.

## 실행

```sh
uv run python kiwoom_order.py --account-id 1          # 드라이런(기본) — 페이로드만 출력
uv run python kiwoom_order.py --accounts              # 계좌번호조회
uv run python kiwoom_order.py --account-id 1 --send   # 실제 전송
uv run python test_kiwoom_order.py                    # 단위 검증(네트워크 없음)
```

Actions: `mirror` 워크플로를 수동 실행. `account_id` 입력이 필수, `dry_run`은 기본 true다.
워크플로 입력은 `run:` 스크립트에 보간하지 않고 **env로 받아 인용**한다(직접 보간은 셸 인젝션 →
시크릿 유출). 셸에서 형식을 먼저 거르고 파이썬에서 한 번 더 검증한다.
**스케줄은 일부러 없다** — 실제 전송이 사람 확인을 거치게 한다. 모의계좌에서
충분히 검증한 뒤 cron을 붙인다.

## 아직 확인 못 한 것

- `kt10003`(취소)의 요청 필드명(`orig_ord_no`/`org_ord_no`, 취소수량 필드) 미확정 →
  파이썬 클라이언트에 취소 미구현
- `ka00001` / `kt00018` 응답 필드명 미확정 (`--accounts`는 원본 JSON을 그대로 출력)
- Actions 유동 IP에서 키움 토큰 발급이 되는지 미검증 (분봉 수집과 동일한 리스크)
- 실제 주문 전송은 아직 한 번도 하지 않았다
- `paperBroker.cancelOrder` 단위 테스트 없음 — `vitest.config.ts`에 `@` 별칭이 없어
  주문 취소 API 라우트가 생기면 취소 로직은 lib/trading.ts에 함수로 넣는다
