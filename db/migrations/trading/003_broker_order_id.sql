-- v1.5 키움 모의계좌 미러링 대사용 컬럼. 001_init.sql의 CREATE TABLE에도 있지만
-- 프로덕션 orders는 그 컬럼이 추가되기 전에 생성돼(CREATE TABLE IF NOT EXISTS라
-- 재실행해도 컬럼이 안 붙는다) 실제 테이블엔 없었다. ALTER로 채운다.
-- 재실행 시 duplicate column은 migrate.mjs가 삼킨다(멱등).
ALTER TABLE orders ADD COLUMN broker_order_id TEXT;
