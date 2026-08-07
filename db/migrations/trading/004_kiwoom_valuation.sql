-- 키움 실제 평가값을 저장한다. 웹은 손익을 '현재가-매입가'로만 계산해 수수료·세금·
-- 예상 매도제비용을 안 빼서 키움과 어긋났다. 키움이 기준이므로 키움의 평가손익·
-- 추정예탁자산을 그대로 담아 표시한다. NULL이면(REPLAY·미동기화) 기존대로 계산.
-- 재실행 시 duplicate column은 migrate.mjs가 삼킨다(멱등).
ALTER TABLE positions ADD COLUMN pnl INTEGER;       -- 키움 평가손익(제비용 반영, 부호 있음)
ALTER TABLE accounts  ADD COLUMN est_asset INTEGER;  -- 키움 추정예탁자산(총자산)
