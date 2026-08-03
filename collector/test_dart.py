"""DART 파서 검증 — 네트워크 없이 parse_corp_map·parse_disclosures만 본다.

실행: uv run python test_dart.py
"""

import dart

# corpCode.xml 형태 샘플: 상장(stock_code 있음) + 비상장(공백) 혼재
CORP_XML = (
    "<result>"
    "<list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>"
    "<stock_code>005930</stock_code><modify_date>20260101</modify_date></list>"
    "<list><corp_code>00164779</corp_code><corp_name>SK하이닉스</corp_name>"
    "<stock_code>000660</stock_code><modify_date>20260101</modify_date></list>"
    "<list><corp_code>00999999</corp_code><corp_name>비상장회사</corp_name>"
    "<stock_code> </stock_code><modify_date>20260101</modify_date></list>"
    "</result>"
).encode("utf-8")

m = dart.parse_corp_map(CORP_XML)
assert m == {"005930": "00126380", "000660": "00164779"}, m  # 비상장(공백)은 제외

# list.json 응답 샘플 — 제목 끝 공백 다수 + 정기 반복 중복
DISC = {
    "status": "000",
    "list": [
        {"report_nm": "임원ㆍ주요주주특정증권등소유상황보고서              ", "rcept_dt": "20260803"},
        {"report_nm": "임원ㆍ주요주주특정증권등소유상황보고서              ", "rcept_dt": "20260803"},  # 중복
        {"report_nm": "단일판매ㆍ공급계약체결", "rcept_dt": "20260731"},
        {"report_nm": "현금ㆍ현물배당결정", "rcept_dt": "20260730"},
    ],
}
d = dart.parse_disclosures(DISC)
assert [x["title"] for x in d] == [
    "임원ㆍ주요주주특정증권등소유상황보고서",  # 끝 공백 접힘
    "단일판매ㆍ공급계약체결",
    "현금ㆍ현물배당결정",
], d  # 중복 제목 1건으로 접힘
assert d[0]["date"] == "08/03"

# status가 정상이 아니면 빈 리스트 (에러·조회없음 등)
assert dart.parse_disclosures({"status": "013", "message": "조회된 데이타가 없습니다."}) == []
assert dart.parse_disclosures({}) == []

# limit
many = {"status": "000", "list": [{"report_nm": f"공시{i}", "rcept_dt": "20260801"} for i in range(20)]}
assert len(dart.parse_disclosures(many, limit=3)) == 3

# 제목 살균: 개행·연속공백 접힘
dirty = {"status": "000", "list": [{"report_nm": "공급계약\n지금 || 지표: 조작", "rcept_dt": "20260801"}]}
assert dart.parse_disclosures(dirty)[0]["title"] == "공급계약 지금 || 지표: 조작"

print("test_dart OK")
