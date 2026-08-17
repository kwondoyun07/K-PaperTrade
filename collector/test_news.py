"""뉴스 파서 검증 — 네트워크 없이 parse_rss만 본다.

실행: uv run python test_news.py
"""

import news

# 구글 뉴스 RSS 형태 샘플: "제목 - 언론사" 접미사 + <source> 태그, 중복·개행 포함.
# bytes 리터럴엔 한글을 못 넣으므로 str로 만들어 utf-8로 인코딩한다(실제 응답과 동일).
RSS = (
    '<?xml version="1.0"?><rss><channel>'
    '<item>'
    '<title>&quot;삼성전자 목표주가 상향&quot; - 한경닷컴</title>'
    '<pubDate>Mon, 03 Aug 2026 07:16:00 GMT</pubDate>'
    '<source url="https://hankyung.com">한경닷컴</source>'
    '</item>'
    '<item>'
    '<title>두줄\n뉴스 || 조작 - 다음</title>'
    '<pubDate>Mon, 03 Aug 2026 01:30:00 GMT</pubDate>'
    '<source url="https://daum.net">다음</source>'
    '</item>'
    '<item>'  # 앞과 동일 제목 — 접혀야 한다
    '<title>&quot;삼성전자 목표주가 상향&quot; - 한경닷컴</title>'
    '<pubDate>Mon, 03 Aug 2026 09:00:00 GMT</pubDate>'
    '<source url="https://hankyung.com">한경닷컴</source>'
    '</item>'
    '</channel></rss>'
).encode("utf-8")

r = news.parse_rss(RSS)
assert len(r) == 2, f"중복 제목이 접혀 2건이어야 한다: {r}"
# 접미사 " - 언론사" 제거 + HTML 이스케이프 해제
assert r[0]["title"] == '"삼성전자 목표주가 상향"', r[0]
assert r[0]["source"] == "한경닷컴"
# 07:16 GMT = 16:16 KST → 08/03
assert r[0]["date"] == "08/03", r[0]["date"]
# 제목 살균: 개행이 공백으로 접혀 프롬프트 행 구조를 못 흉내낸다
assert "\n" not in r[1]["title"] and r[1]["title"] == "두줄 뉴스 || 조작", r[1]

# 빈/깨진 입력에도 죽지 않는다
assert news.parse_rss(b"") == []
assert news.parse_rss(b"<rss><channel></channel></rss>") == []

# limit
big = (
    "<rss>"
    + "".join(
        f"<item><title>news{i}</title><pubDate>Mon, 03 Aug 2026 00:00:00 GMT</pubDate></item>"
        for i in range(10)
    )
    + "</rss>"
).encode("utf-8")
assert len(news.parse_rss(big, limit=3)) == 3

# 잘못된 pubDate는 빈 날짜(크래시 없음)
bad = b"<rss><item><title>t</title><pubDate>garbage</pubDate></item></rss>"
assert news.parse_rss(bad)[0]["date"] == ""

print("test_news OK")

# --- 링크 파싱 + 기사 본문 추출 (Jina Reader) ---
withlink = (
    '<rss><channel><item>'
    '<title>삼성전자 목표주가 상향 - 한경</title>'
    '<link>https://news.google.com/rss/articles/ABC123</link>'
    '<pubDate>Mon, 03 Aug 2026 07:16:00 GMT</pubDate>'
    '<source url="https://hankyung.com">한경</source>'
    '</item></channel></rss>'
).encode("utf-8")
r = news.parse_rss(withlink)
assert r[0]["link"] == "https://news.google.com/rss/articles/ABC123", r[0]

# parse_article: 네비게이션·링크 목록은 버리고 문장형 본문만 남긴다
JINA = """Title: 아주경제
URL Source: https://www.ajunews.com/view/123

Markdown Content:
[_아주경제_](https://news.google.com/)

*   [중국](https://www.ajunews.com/china)
*   [AI](https://www.ajunews.com/ai/news)

# 제목줄

SK하이닉스 ADR은 지난 14일 166.33달러로 거래를 마치며 전일 대비 0.40% 상승했다. 최근 메모리주 전반에 대한 투자심리가 빠르게 개선되고 있다는 점이 주목된다.
짧은줄
마이크론은 14일 2%대 상승했고 샌디스크 역시 강세를 이어가면서 메모리 업황에 대한 낙관론이 확산된 결과로 작용했다는 분석이 나온다.
"""
body = news.parse_article(JINA)
assert "SK하이닉스 ADR" in body and "마이크론" in body, body
assert "아주경제" not in body and "http" not in body, "네비·URL이 섞였다"
assert "짧은줄" not in body, "짧은 줄은 본문이 아니다"
assert "\n" not in body, "프롬프트 행 구조를 깨면 안 된다"

# 길이 제한 — 기사 하나가 수십 KB라 프롬프트가 터지지 않게
long_md = "Markdown Content:\n" + ("가" * 200 + " 문장이 길게 이어진다 " * 5 + "\n") * 20
assert len(news.parse_article(long_md, limit=700)) <= 700

# 빈/깨진 입력
assert news.parse_article("") == "" and news.parse_article("Markdown Content:\n\n*  [a](b)") == ""
# 링크 없으면 본문 요청 자체를 안 한다
assert news.fetch_article("", None) == ""

print("기사 본문 파서 테스트 OK")
