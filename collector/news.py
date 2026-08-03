"""무료 뉴스 수집 — 구글 뉴스 RSS. 종목명으로 최근 헤드라인을 판단 신호로.

키·등록 불필요(네이버 검색 API·빅카인즈는 신규 발급이 막혀 있어 이 경로를 쓴다).
종목명으로 RSS를 받아 제목·출처·날짜를 뽑는다. 감성 판단은 claude가 헤드라인을 보고 한다.

파싱(parse_rss)은 순수 함수로 분리해 네트워크 없이 검증한다(test_news.py). 실패·빈
결과는 빈 리스트 — 뉴스는 보조 신호라 없으면 기술·컨센서스·공시 지표만으로 이어간다.
"""

import html
import logging
import re
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def _clean(v: object, limit: int) -> str:
    """헤드라인은 외부 텍스트 — 개행·연속공백을 접고 길이를 잘라 프롬프트 행 구조를
    흉내내지 못하게 한다(주입 표면 축소)."""
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def _mmdd(rfc822: str) -> str:
    try:
        return parsedate_to_datetime(rfc822).astimezone(KST).strftime("%m/%d")
    except Exception:
        return ""


def parse_rss(xml_bytes: bytes, limit: int = 5) -> list[dict]:
    """구글 뉴스 RSS → 최근 헤드라인 [{title, source, date}]. 순수 함수.

    RSS <title>은 "제목 - 언론사" 형태라 <source> 태그로 접미사를 떼어낸다.
    같은 제목은 접는다.
    """
    text = xml_bytes.decode("utf-8", "replace")
    out: list[dict] = []
    seen: set[str] = set()
    for block in re.findall(r"<item>(.*?)</item>", text, re.S):
        tm = re.search(r"<title>(.*?)</title>", block, re.S)
        if not tm:
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", tm.group(1))).strip()
        sm = re.search(r"<source[^>]*>(.*?)</source>", block, re.S)
        source = html.unescape(sm.group(1)).strip() if sm else ""
        if source and title.endswith(f" - {source}"):
            title = title[: -(len(source) + 3)].strip()
        title = _clean(title, 80)
        if not title or title in seen:
            continue
        seen.add(title)
        dm = re.search(r"<pubDate>(.*?)</pubDate>", block)
        out.append({"title": title, "source": _clean(source, 20), "date": _mmdd(dm.group(1)) if dm else ""})
        if len(out) >= limit:
            break
    return out


def fetch_news(name: str, client: httpx.Client) -> list[dict]:
    url = f"https://news.google.com/rss/search?q={quote(name)}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        r = client.get(url, headers={"User-Agent": _UA}, timeout=10.0)
        r.raise_for_status()
        return parse_rss(r.content)
    except Exception as e:  # 네트워크·구조 변경 — 보조 신호라 조용히 스킵
        log.warning("뉴스 조회 실패 %s: %s", name, e)
        return []


def fetch_many(names_by_ticker: dict[str, str]) -> dict[str, list[dict]]:
    """유니버스 종목의 최근 뉴스 헤드라인. 이름 없는 종목·실패는 빠진다."""
    out: dict[str, list[dict]] = {}
    with httpx.Client(follow_redirects=True) as c:
        first = True
        for t, name in names_by_ticker.items():
            if not name:
                continue
            if not first:
                time.sleep(0.2)  # 연속 호출 예의
            first = False
            items = fetch_news(name, c)
            if items:
                out[t] = items
    if out:
        log.info("뉴스 수집: %d종목", len(out))
    return out
