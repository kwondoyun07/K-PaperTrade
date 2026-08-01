"""Turso(libSQL) HTTP 헬퍼 — SDK 의존성 없이 v2/pipeline 엔드포인트 직접 호출.

모든 적재 SQL은 upsert(ON CONFLICT DO UPDATE)로 작성해 재실행이 멱등하도록 한다.
"""

import os

import httpx


def _arg(v: object) -> dict:
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


class Turso:
    def __init__(self, url: str, token: str):
        self.url = url.replace("libsql://", "https://").rstrip("/")
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {token}"}, timeout=30.0
        )

    @classmethod
    def from_env(cls, db: str) -> "Turso | None":
        """db: 'KRX_MARKET' | 'TRADING'. env 미설정이면 None(로컬 드라이런 허용)."""
        url = os.environ.get(f"TURSO_{db}_URL")
        token = os.environ.get(f"TURSO_{db}_AUTH_TOKEN")
        if not url or not token:
            return None
        return cls(url, token)

    def execute(self, sql: str, args: tuple = ()) -> None:
        self.execute_batch([(sql, args)])

    def query(self, sql: str, args: tuple = ()) -> list[dict]:
        """SELECT 실행 후 행을 dict 리스트로 반환 (hrana v2 값 디코딩)."""
        r = self._client.post(
            f"{self.url}/v2/pipeline",
            json={
                "requests": [
                    {"type": "execute", "stmt": {"sql": sql, "args": [_arg(a) for a in args]}},
                    {"type": "close"},
                ]
            },
        )
        r.raise_for_status()
        res = r.json()["results"][0]
        if res.get("type") == "error":
            raise RuntimeError(f"turso 오류: {res.get('error')}")
        result = res["response"]["result"]
        cols = [c["name"] for c in result["cols"]]
        return [
            {c: _decode(v) for c, v in zip(cols, row)}
            for row in result["rows"]
        ]

    def execute_batch(self, stmts: list[tuple[str, tuple]], chunk: int = 200) -> None:
        for i in range(0, len(stmts), chunk):
            requests = [
                {
                    "type": "execute",
                    "stmt": {"sql": sql, "args": [_arg(a) for a in args]},
                }
                for sql, args in stmts[i : i + chunk]
            ]
            requests.append({"type": "close"})
            r = self._client.post(f"{self.url}/v2/pipeline", json={"requests": requests})
            r.raise_for_status()
            for res in r.json().get("results", []):
                if res.get("type") == "error":
                    raise RuntimeError(f"turso 오류: {res.get('error')}")


def _decode(v: dict):
    t = v.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    return v.get("value")
