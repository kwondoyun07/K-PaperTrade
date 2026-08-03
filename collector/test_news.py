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
