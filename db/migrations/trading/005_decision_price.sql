-- ret_d5의 기준가 결함 수정용 컬럼.
-- 기존엔 '판단일 종가'를 기준가로 썼다. 그러면 같은 날·같은 종목의 BUY와 HOLD가
-- 글자 그대로 같은 수익률을 받아(판단이 아니라 종목·날짜를 잰다), 게다가 AI는 그날
-- 오르는 종목을 사므로 이미 오른 종가가 진입가가 돼 BUY에만 핸디캡이 실린다
-- (실측 2026-08-16: 판단 당일 등락 BUY +2.55% / HOLD -2.06% → 격차가 3.91pp 뒤집힘).
-- decision_price: 판단 시점에 AI가 실제로 본 가격(decide.py가 기록).
-- ret_basis: 그 행의 수익률을 무엇을 기준가로 계산했는지.
--            분석에서 믿을 수 있는 행은 ret_basis='decision' 뿐이다.
--            'close' = decision_price 없는 폴백, NULL = 이 컬럼 도입 전 계산분(둘 다 폴백).
-- 재실행 시 duplicate column은 migrate.mjs가 삼킨다(멱등).
ALTER TABLE ai_decisions ADD COLUMN decision_price REAL;
ALTER TABLE ai_decisions ADD COLUMN ret_basis TEXT;
