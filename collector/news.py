"""무료 뉴스 수집 — 구글 뉴스 RSS. 종목명으로 최근 헤드라인을 판단 신호로.

키·등록 불필요(네이버 검색 API·빅카인즈는 신규 발급이 막혀 있어 이 경로를 쓴다).
종목명으로 RSS를 받아 제목·출처·날짜를 뽑는다. 감성 판단은 claude가 헤드라인을 보고 한다.

파싱(parse_rss)은 순수 함수로 분리해 네트워크 없이 검증한다(test_news.py). 실패·빈
결과는 빈 리스트 — 뉴스는 보조 신호라 없으면 기술·컨센서스·공시 지표만으로 이어간다.
"""

import html
import logging
import os
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
        lm = re.search(r"<link>(.*?)</link>", block, re.S)
        out.append({
            "title": title,
            "source": _clean(source, 20),
            "date": _mmdd(dm.group(1)) if dm else "",
            # 본문 수집용. 구글 뉴스 링크는 언론사로 리다이렉트된다(Jina가 따라간다).
            "link": html.unescape(lm.group(1)).strip() if lm else "",
        })
        if len(out) >= limit:
            break
    return out


def parse_article(markdown: str, limit: int = 700) -> str:
    """Jina Reader 응답 → 기사 본문 요지.

    응답에는 네비게이션·링크 목록이 잔뜩 섞여 있다. 문장형 줄(길고, 목록·헤더·URL이
    아닌 줄)만 남겨 본문만 뽑는다. 순수 함수 — test_news.py가 직접 검증한다.
    """
    body = markdown.split("Markdown Content:", 1)[-1]
    prose = [
        ln.strip()
        for ln in body.splitlines()
        if len(ln.strip()) > 60
        and not ln.lstrip().startswith(("*", "[", "#", "|", "_", "-", ">"))
        and "http" not in ln
    ]
    return _clean(" ".join(prose), limit)


def fetch_article(link: str, client: httpx.Client) -> str:
    """Jina Reader로 기사 본문. 실패는 빈 문자열 — 그러면 제목만으로 판단한다.

    JINA_API_KEY(무료 발급)가 있으면 인증 호출로 안정적이다. **키 없이도 되지만**
    연속 호출하면 Cloudflare 봇 체크("Just a moment...")에 403으로 막힌다(실측).
    공용 IP인 GitHub Actions에서는 특히 잘 막히므로, 본문은 '되면 좋은' 보조 신호로만
    쓴다 — 실패해도 헤드라인 판단은 그대로 간다.
    """
    if not link:
        return ""
    headers = {"User-Agent": _UA}
    key = os.environ.get("JINA_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        r = client.get(f"https://r.jina.ai/{link}", headers=headers, timeout=30.0)
        r.raise_for_status()
        return parse_article(r.text)
    except Exception as e:  # 보조 신호 — 본문이 없으면 제목만으로 판단한다
        log.warning("본문 조회 실패(%s) — 제목만으로 진행", str(e)[:80])
        return ""


def fetch_news(name: str, client: httpx.Client) -> list[dict]:
    url = f"https://news.google.com/rss/search?q={quote(name)}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        r = client.get(url, headers={"User-Agent": _UA}, timeout=10.0)
        r.raise_for_status()
        return parse_rss(r.content)
    except Exception as e:  # 네트워크·구조 변경 — 보조 신호라 조용히 스킵
        log.warning("뉴스 조회 실패 %s: %s", name, e)
        return []


def fetch_many(names_by_ticker: dict[str, str], bodies: int = 1) -> dict[str, list[dict]]:
    """유니버스 종목의 최근 뉴스. 이름 없는 종목·실패는 빠진다.

    bodies>0이면 종목당 최신 기사 그만큼의 **본문**까지 받는다(Jina Reader). 제목만으로는
    호재·악재가 애매한 경우가 많아 판단 재료가 얕다. 본문은 종목당 1건이 기본 — 기사
    하나가 수십 KB라 프롬프트가 급격히 커지고, 장중 시간(판단은 몇 분 안에 끝나야 한다)도
    잡아먹는다. bodies=0이면 기존처럼 제목만.
    """
    out: dict[str, list[dict]] = {}
    blocked = False  # 본문 소스가 막힌 런에서 종목마다 재시도하지 않기 위한 차단기
    with httpx.Client(follow_redirects=True) as c:
        first = True
        for t, name in names_by_ticker.items():
            if not name:
                continue
            if not first:
                time.sleep(0.2)  # 연속 호출 예의
            first = False
            items = fetch_news(name, c)
            if bodies and not blocked:
                for it in items[:bodies]:
                    it["body"] = fetch_article(it.get("link", ""), c)
                    if not it["body"]:
                        # Jina가 막히면(Cloudflare) 이 런에서는 계속 막힌다 — IP 단위라
                        # 종목마다 재시도해봐야 시간만 쓴다. 이번 런은 제목만으로 간다.
                        blocked = True
                        log.info("본문 수집 중단 — 이번 판단은 헤드라인만 사용")
                        break
            if items:
                out[t] = items
    if out:
        n = sum(1 for v in out.values() for x in v if x.get("body"))
        log.info("뉴스 수집: %d종목 (본문 %d건)", len(out), n)
    return out
