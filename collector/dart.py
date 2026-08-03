"""무료 공시 수집 — DART 오픈API(전자공시). 종목별 최근 공시 제목을 판단 신호로.

DART_API_KEY(무료 발급)가 필요하다. 키가 없거나 실패하면 빈 결과 — 공시는 판단을
풍부하게 하는 보조 신호라 없으면 기술·컨센서스 지표만으로 이어간다.

list.json은 corp_code로 필터한다. 종목코드↔corp_code 매핑은 corpCode.xml(전 종목,
zip)로 받는다. 파싱(parse_*)은 순수 함수로 분리해 네트워크 없이 검증한다(test_dart.py).

ponytail: corpCode(3.5MB)를 decide 실행마다 받는다. 호출량은 DART 일 20k 한도 대비
미미(실행당 corpCode 1 + 종목당 1)하나, 잦아지면 Turso에 주 1회 캐시하는 편이 낫다.
"""

import io
import logging
import os
import re
import time
import zipfile
from xml.etree import ElementTree as ET

import httpx

log = logging.getLogger(__name__)
_BASE = "https://opendart.fss.or.kr/api"


def _clean(v: object, limit: int = 60) -> str:
    """공시 제목은 외부 텍스트 — 개행·연속공백(제목 끝 공백 다수)을 접고 길이를 자른다."""
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def _mmdd(yyyymmdd: object) -> str:
    s = str(yyyymmdd or "")
    return f"{s[4:6]}/{s[6:8]}" if len(s) == 8 else s


def parse_corp_map(xml_bytes: bytes) -> dict[str, str]:
    """CORPCODE.xml → {6자리 종목코드: corp_code}. 상장(stock_code 있음)만 남긴다."""
    root = ET.fromstring(xml_bytes)
    out: dict[str, str] = {}
    for e in root.iter("list"):
        sc = (e.findtext("stock_code") or "").strip()
        cc = (e.findtext("corp_code") or "").strip()
        if sc and cc:
            out[sc.zfill(6)] = cc
    return out


def parse_disclosures(payload: dict, limit: int = 5) -> list[dict]:
    """list.json 응답 → 최근 공시 [{title, date}]. 같은 제목(정기 반복분)은 접는다."""
    if payload.get("status") != "000":
        return []
    seen: set[str] = set()
    out: list[dict] = []
    for it in payload.get("list", []):
        title = _clean(it.get("report_nm"))
        if not title or title in seen:
            continue
        seen.add(title)
        out.append({"title": title, "date": _mmdd(it.get("rcept_dt"))})
        if len(out) >= limit:
            break
    return out


def corp_map(key: str, client: httpx.Client) -> dict[str, str]:
    r = client.get(f"{_BASE}/corpCode.xml", params={"crtfc_key": key}, timeout=30.0)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    return parse_corp_map(z.read(z.namelist()[0]))


def fetch_many(tickers: list[str], bgn_de: str) -> dict[str, list[dict]]:
    """유니버스 종목의 bgn_de(YYYYMMDD) 이후 공시. 키 없음·실패는 빈 dict(보조 신호)."""
    key = os.environ.get("DART_API_KEY")
    if not key:
        log.info("DART_API_KEY 미설정 — 공시 수집 건너뜀")
        return {}
    out: dict[str, list[dict]] = {}
    with httpx.Client(timeout=30.0) as c:
        try:
            cm = corp_map(key, c)
        except Exception as e:  # corpCode 실패면 공시 전량 스킵 — 판단은 계속된다
            log.warning("DART corpCode 실패 — 공시 수집 스킵: %s", e)
            return {}
        for i, t in enumerate(tickers):
            cc = cm.get(t)
            if not cc:
                continue
            if i:
                time.sleep(0.1)  # 연속 호출 예의
            try:
                r = c.get(
                    f"{_BASE}/list.json",
                    params={"crtfc_key": key, "corp_code": cc, "bgn_de": bgn_de, "page_count": "30"},
                    timeout=10.0,
                )
                ds = parse_disclosures(r.json())
            except Exception as e:
                log.warning("DART 공시 조회 실패 %s: %s", t, e)
                continue
            if ds:
                out[t] = ds
    if out:
        log.info("DART 공시 수집: %d종목", len(out))
    return out
