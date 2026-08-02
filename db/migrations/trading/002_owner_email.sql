-- 계좌·리플레이 세션에 소유자를 기록한다. 이 컬럼이 없으면 로그인한 아무나
-- accountId만 바꿔 남의 계좌에 주문·조회할 수 있다(계좌 간 IDOR). 라우트가
-- 세션 이메일과 이 값을 대조한다. 배치(x-cron-secret)는 소유와 무관하게 통과한다.
--
-- SQLite ALTER는 IF NOT EXISTS를 지원하지 않아 재실행 시 "duplicate column"으로
-- 던진다. migrate.mjs가 그 오류만 삼켜 멱등을 유지한다.
ALTER TABLE accounts ADD COLUMN owner_email TEXT;
ALTER TABLE replay_sessions ADD COLUMN owner_email TEXT;
