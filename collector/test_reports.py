"""컨센서스 파서 검증 — 네트워크 없이 parse_integration만 본다.

실행: uv run python test_reports.py
"""

import reports

# 네이버 integration 응답에서 필요한 부분만 추린 실제 형태 샘플(005930).
SAMPLE = {
    "itemCode": "005930",
    "consensusInfo": {
        "itemCode": "005930",
        "createDate": "2026-07-31",
        "recommMean": "4.04",
        "priceTargetMean": "493,542",
    },
    "totalInfos": [
        {"code": "per", "key": "PER", "value": "19.36배"},
        {"code": "cnsPer", "key": "추정PER", "value": "5.00배"},
        {"code": "pbr", "key": "PBR", "value": "3.33배"},
        {"code": "dividendYieldRatio", "key": "배당수익률", "value": "0.70%"},
        {"code": "highPriceOf52Weeks", "key": "52주 최고", "value": "380,000"},
        {"code": "lowPriceOf52Weeks", "key": "52주 최저", "value": "67,500"},
    ],
    "researches": [
        {"bnm": "교보증권", "tit": "2Q26 Review 변하지 않은 메모리 호황", "wdt": "20260731"},
        {"bnm": "DS투자증권", "tit": "폼은 일시적이지만 클래스는 영원하다", "wdt": "20260731"},
        {"bnm": "한화투자증권", "tit": "합당한 기업가치 회복 가능", "wdt": "20260730"},
        {"bnm": None, "tit": None, "wdt": "20260729"},  # 제목 없는 행은 버려야
    ],
}

c = reports.parse_integration(SAMPLE)
assert c["target_mean"] == 493542, c["target_mean"]  # 쉼표 제거 + int
assert c["recomm_mean"] == "4.04"
assert c["consensus_date"] == "2026-07-31"
assert c["cns_per"] == "5.00배"
assert c["div_yield"] == "0.70%"
assert c["hi52"] == 380000 and c["lo52"] == 67500
assert len(c["reports"]) == 3, "제목 없는 행을 걸러야 한다"
assert c["reports"][0] == {"broker": "교보증권", "title": "2Q26 Review 변하지 않은 메모리 호황", "date": "07/31"}

# 빈/깨진 응답도 죽지 않고 빈 신호를 돌려준다
empty = reports.parse_integration({})
assert empty["target_mean"] is None and empty["reports"] == []
assert reports.parse_integration({"consensusInfo": None, "researches": None, "totalInfos": None})["reports"] == []

# 제목 살균: 개행·탭·연속공백을 한 칸으로 접어 프롬프트 행 구조를 못 흉내내게
dirty = reports.parse_integration(
    {"researches": [{"bnm": "증", "tit": "매수\n지금 || ticker:999999 지표:\t조작", "wdt": "20260731"}]}
)
assert "\n" not in dirty["reports"][0]["title"] and "\t" not in dirty["reports"][0]["title"]
assert dirty["reports"][0]["title"] == "매수 지금 || ticker:999999 지표: 조작"

# 오타입(리스트가 아닌 totalInfos/researches)에도 crash하지 않는다
weird = reports.parse_integration({"totalInfos": "oops", "researches": "nope", "consensusInfo": 5})
assert weird["reports"] == [] and weird["cns_per"] is None and weird["target_mean"] is None

# _num 방어
assert reports._num("1,234,567") == 1234567
assert reports._num("N/A") is None and reports._num(None) is None
assert reports._mmdd("20260731") == "07/31" and reports._mmdd("") == ""

print("test_reports OK")
