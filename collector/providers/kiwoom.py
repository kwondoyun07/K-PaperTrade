"""KiwoomRestProvider — 서버점검 종료 후 주력 프로바이더가 될 자리 (v1).

지금은 스텁만 둔다. 구현 시 참고:
- openapi.kiwoom.com, 모의투자용 앱키는 실전과 별도 발급
- 토큰 발급 → 분봉 차트 TR 호출
- 토큰 IP 제약이 있으므로 GitHub Actions 배치에서 발급·호출을 같은 런에 수행
  (Vercel 서버리스에서 직접 호출 금지 — 핸드오프 §8)
"""


class KiwoomRestProvider:
    def __init__(self, app_key: str | None = None, app_secret: str | None = None):
        raise NotImplementedError("키움 REST API 서버점검 종료 후 구현 (v1)")
