"""BUY vs HOLD 성과 진단 — 읽기 전용 분석 배치.

ai_decisions.ret_d5를 그대로 평균내면 "BUY가 HOLD보다 못하다"가 나온다. 이 스크립트는
그 숫자가 실제 예측력 차이인지, 아니면 표본·측정 방식의 산물인지를 갈라내려고 만들었다.

수익률은 ret_d5 컬럼을 믿지 않고 daily_prices에서 매번 다시 계산한다. 컬럼은 마감 배치가
채우는 것이라 최근 판단은 비어 있고(=표본이 과거로 쏠림), 그 편향 자체가 진단 대상이다.

측정 규칙 두 가지 — 이전 판 리포트가 틀린 결론을 낸 원인이라 명시해 둔다.
  1) '판단 직전 N일' 같은 과거 구간의 종점은 항상 **전일 종가**다. 판단일 종가를 종점으로
     쓰면 10:30 판단 시점에 알 수 없는 5시간 뒤 값이 설명변수에 섞인다(선견편향).
  2) 미래 수익률의 진입가(기준가)는 결론을 뒤집을 만큼 민감하다. 그래서 [1]에서 항상
     판단일 종가 / 전일 종가 / 체결가 세 기준을 나란히 출력한다.

실행:
  uv run --env-file ../.env python analyze.py
  uv run --env-file ../.env python analyze.py --base prev --horizon 3
"""

import argparse
import io
import statistics as st
import sys
from bisect import bisect_left
from collections import defaultdict
from math import exp, lgamma, log, sqrt

from turso import Turso

# 판단 근거(reason_summary)를 4갈래 입력 중 무엇에 기댔는지로 분류하는 키워드.
# 한 판단이 여러 갈래에 걸리면 전부 카운트한다(배타 분류 아님).
SIGNAL_KEYWORDS = {
    "기술": ["장중", "VWAP", "MA5", "MA20", "이평", "고가권", "저점", "반등", "추세",
             "모멘텀", "거래량", "고점", "낙폭", "이격", "20일", "5일"],
    "컨센서스": ["목표가", "괴리", "리포트", "투자의견", "컨센", "PER", "PBR", "저평가", "밸류"],
    "공시": ["공시", "자사주", "소각", "지분", "증자", "배당"],
    "뉴스": ["뉴스", "수주", "호재", "실적", "서프라이즈", "출시", "계약", "지라시"],
}

BASES = {"close": (0, "판단일 종가"), "prev": (-1, "전일 종가")}


def pct(v: float | None) -> str:
    return "  n/a " if v is None else f"{v:+6.2f}"


# -------------------------------------------------- 유의성 (scipy 없이)

def _betacf(a: float, b: float, x: float) -> float:
    tiny, qab, qap, qam = 1e-300, a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (tiny if abs(d) < tiny else d)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)),
                   -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d, c = 1 + aa * d, 1 + aa / c
            d = 1 / (tiny if abs(d) < tiny else d)
            c = tiny if abs(c) < tiny else c
            h *= d * c
        if abs(d * c - 1) < 3e-11:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """정규화 불완전 베타 I_x(a,b) — t분포 꼬리확률을 얻는 표준 경로."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    bt = exp(lgamma(a + b) - lgamma(a) - lgamma(b) + a * log(x) + b * log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1 - bt * _betacf(b, a, 1 - x) / b


def t_p(t: float, df: float) -> float:
    """양측 p값."""
    return _betai(df / 2, 0.5, df / (df + t * t))


def ttest1(xs: list[float]) -> str:
    """1표본(짝지은 차이) t검정. 유효 표본은 관측 수가 아니라 여기 들어온 xs의 길이다."""
    n = len(xs)
    if n < 2:
        return f"n={n} — 검정 불가"
    m, sd = st.mean(xs), st.stdev(xs)
    if sd == 0:
        return f"n={n} 평균 {m:+.2f} sd=0 — 검정 불가"
    t = m / (sd / sqrt(n))
    return f"n={n} 평균 {m:+.2f}pp sd={sd:.2f} t={t:+.2f} df={n-1} p={t_p(t, n - 1):.3f}"


def ttest2(a: list[float], b: list[float]) -> str:
    """Welch 2표본 t검정. 관측을 독립으로 취급하므로 클러스터가 있으면 p가 과소평가된다."""
    if len(a) < 2 or len(b) < 2:
        return "검정 불가"
    va, vb = st.variance(a) / len(a), st.variance(b) / len(b)
    if va + vb == 0:
        return "검정 불가"
    t = (st.mean(a) - st.mean(b)) / sqrt(va + vb)
    df = (va + vb) ** 2 / (va**2 / (len(a) - 1) + vb**2 / (len(b) - 1))
    return f"n={len(a)}/{len(b)} t={t:+.2f} df={df:.1f} p={t_p(t, df):.3f}"


# -------------------------------------------------- 가격

class Prices:
    """티커별 (거래일, 종가) 배열. 거래일 인덱스 오프셋 기준으로 구간 수익률(%)을 준다."""

    def __init__(self, mdb: Turso, tickers: list[str], since: str):
        self.base = 0  # 진입가 오프셋: 0=판단일 종가, -1=전일 종가
        self.px: dict[str, tuple[list[str], list[float]]] = {}
        for tk in tickers:
            rows = mdb.query(
                "SELECT date, close FROM daily_prices WHERE ticker = ? AND date >= ? ORDER BY date",
                (tk, since),
            )
            self.px[tk] = ([str(r["date"]) for r in rows], [float(r["close"]) for r in rows])

    def add_index(self, mdb: Turso, code: str, since: str) -> bool:
        rows = mdb.query(
            "SELECT date, close FROM indices WHERE code = ? AND date >= ? ORDER BY date",
            (code, since),
        )
        self.px[code] = ([str(r["date"]) for r in rows], [float(r["close"]) for r in rows])
        return bool(rows)

    def price(self, ticker: str, day: str, off: int = 0) -> float | None:
        """day의 거래일 인덱스에서 off칸 이동한 종가. day가 휴장일이면 다음 거래일 기준."""
        ds, cs = self.px.get(ticker, ([], []))
        i = bisect_left(ds, day) + off
        return cs[i] if 0 <= i < len(ds) else None

    def ret(self, ticker: str, day: str, frm: int, to: int) -> float | None:
        a, b = self.price(ticker, day, frm), self.price(ticker, day, to)
        return None if not a or not b or a <= 0 else (b / a - 1) * 100

    def fwd(self, ticker: str, day: str, n: int) -> float | None:
        """판단 이후 n거래일 수익률. 진입가는 self.base가 정한다(종점은 항상 day+n)."""
        return self.ret(ticker, day, self.base, n)

    def back(self, ticker: str, day: str, n: int) -> float | None:
        """판단 '직전' n거래일 수익률 — 종점은 전일 종가다(판단 시점에 알 수 있는 값만)."""
        return self.ret(ticker, day, -1 - n, -1)

    def close(self, ticker: str, day: str) -> float | None:
        ds, cs = self.px.get(ticker, ([], []))
        i = bisect_left(ds, day)
        return cs[i] if i < len(ds) and ds[i] == day else None


def mean(xs: list[float]) -> float | None:
    return st.mean(xs) if xs else None


def line(label: str, xs: list[float], width: int = 26) -> str:
    if not xs:
        return f"  {label:<{width}} n=  0"
    return (f"  {label:<{width}} n={len(xs):3}  평균 {mean(xs):+6.2f}  "
            f"중앙 {st.median(xs):+6.2f}  승률 {100*sum(x > 0 for x in xs)/len(xs):5.1f}%")


def split(decs: list[dict], px: Prices, H: int) -> tuple[list[float], list[float]]:
    out = []
    for act in ("BUY", "HOLD"):
        out.append([r for d in decs if d["action"] == act
                    and (r := px.fwd(d["ticker"], d["ts"][:10], H)) is not None])
    return out[0], out[1]


# ---------------------------------------------------------------- 섹션들


def sec_sensitivity(decs: list[dict], px: Prices, H: int, fills: list[dict]) -> None:
    """결론의 부호가 진입가 정의 하나로 뒤집힌다. 그래서 이게 첫 섹션이다."""
    print(f"\n[1] 기준가(진입가) 민감도 — d{H} 격차가 진입가 정의에 얼마나 흔들리는가")
    print("    진입가            BUY                HOLD               차이")
    keep = px.base
    for key, (off, label) in BASES.items():
        px.base = off
        b, h = split(decs, px, H)
        if not b or not h:
            continue
        print(f"    {label:<14} n={len(b):3} {mean(b):+6.2f}      "
              f"n={len(h):3} {mean(h):+6.2f}      {mean(b) - mean(h):+6.2f}pp")
    px.base = keep

    # 부호가 뒤집히는 이유: 판단 당일 등락이 액션과 강하게 얽혀 있다.
    print("\n    이유 — 판단 '당일'(전일 종가→판단일 종가) 등락:")
    for act in ("BUY", "HOLD", "SELL"):
        xs = [r for d in decs if d["action"] == act
              and (r := px.ret(d["ticker"], d["ts"][:10], -1, 0)) is not None]
        print(line(f"{act} 당일등락", xs))
    print("    → AI는 그날 오르고 있는 종목을 산다. 진입가를 '판단일 종가'로 잡으면 이미 오른 값이")
    print("      분모가 되어 BUY에 기계적 핸디캡이 실린다. 둘 다 답이 아니라 서로 다른 질문이다:")
    print("      판단일 종가 = '판단 후 종가에 사면?'(실행 가능, 당일 등락을 진입가에 포함)")
    print("      전일 종가   = '신호가 뜬 뒤 총 수익은?'(실행 불가능한 가격, 당일 등락을 성과에 포함)")

    # 세 번째 기준: 실제 체결가. BUY만 존재해 대조군이 없다는 사실 자체가 결론이다.
    xs = [r for f in fills if (r := f["ret"]) is not None]
    nbuy = sum(f["side"] == "BUY" for f in fills)
    print(line("체결가 기준 실현 d%d(BUY만)" % H, xs))
    print(f"    (체결가는 실제 BUY 주문 {nbuy}건 중 d{H} 종점이 있는 {len(xs)}건에만 존재한다. HOLD는 주문 자체가"
          " 없어 대조군이 없으므로 이 기준으로는 BUY vs HOLD 비교가 원리적으로 불가능하다.)")


def sec_coverage(decs: list[dict], H: int) -> None:
    print(f"\n[2] 표본 커버리지 — ret_d{H}가 어느 구간에만 존재하는가")
    print("    날짜        BUY(기록/d5채움)  HOLD(기록/d5채움)  SELL")
    per = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for d in decs:
        cell = per[d["ts"][:10]][d["action"]]
        cell[0] += 1
        cell[1] += d["ret_d5"] is not None
    for day in sorted(per):
        a = per[day]
        print(f"    {day}   {a['BUY'][0]:3}/{a['BUY'][1]:<3}          "
              f"{a['HOLD'][0]:3}/{a['HOLD'][1]:<3}           {a['SELL'][0]:3}")
    filled = [d["ts"][:10] for d in decs if d["ret_d5"] is not None]
    if filled:
        print(f"    → ret_d5가 채워진 판단은 {min(filled)} ~ {max(filled)} 구간뿐. "
              f"이후 판단({len(decs) - len(filled)}건)은 전부 미집계.")


def sec_naive(decs: list[dict], px: Prices, H: int) -> None:
    """'표본 절단이 격차의 최대 원인'이라는 이전 주장을 표본 고정으로 반증한다."""
    print(f"\n[3] 지평선 vs 표본 — 둘을 분리해서 본다")
    hs = sorted({1, 2, 3, 5, H})
    print("    (a) 지평선과 표본을 동시에 바꾼 값 — 이전 리포트가 쓴 표")
    print("    지평선   BUY                 HOLD                차이")
    for n in hs:
        b, h = split(decs, px, n)
        if b and h:
            print(f"    d{n:<6} n={len(b):3} {mean(b):+6.2f}        "
                  f"n={len(h):3} {mean(h):+6.2f}        {mean(b) - mean(h):+6.2f}pp")

    # 표본을 dH 관측 가능한 판단으로 고정하면 지평선 효과만 남는다.
    fixed = [d for d in decs if px.fwd(d["ticker"], d["ts"][:10], H) is not None]
    print(f"\n    (b) 표본을 d{H} 관측 가능한 판단 {len(fixed)}건으로 고정하고 지평선만 축소")
    print("    지평선   BUY                 HOLD                차이")
    for n in hs:
        b, h = split(fixed, px, n)
        if b and h:
            print(f"    d{n:<6} n={len(b):3} {mean(b):+6.2f}        "
                  f"n={len(h):3} {mean(h):+6.2f}        {mean(b) - mean(h):+6.2f}pp")
    print("    → (b)에서도 지평선이 길수록 격차가 벌어지면, 격차는 '표본 절단의 산물'이 아니다.")
    print("      (a)와 (b)의 차이만이 표본 구성 효과다. 두 표를 같이 봐야 구분된다.")


def sec_tickerday(decs: list[dict], px: Prices, H: int) -> None:
    print(f"\n[4] 측정 단위 문제 — ret_d{H}는 '판단'이 아니라 '종목·날짜'의 성질이다")
    td = defaultdict(set)
    for d in decs:
        td[(d["ts"][:10], d["ticker"])].add(d["action"])
    multi = {k: v for k, v in td.items() if len(v) > 1}
    print(f"    같은 종목·같은 날 판단 묶음 {len(td)}개 중 BUY/HOLD가 섞인 묶음 {len(multi)}개.")
    print("    기준가가 하루 단위라 같은 묶음의 BUY와 HOLD는 수익률이 글자 그대로 동일하다.")
    print("    → 하루 3회 판단의 시각 차이는 측정되지 않는다. 사실상 종목·날 단위 비교다.")
    print("    묶음 단위(하루 3회를 1건으로) 재집계:")
    for key, label in (("BUY", "BUY 포함 묶음"), ("HOLD", "HOLD 전원 일치 묶음")):
        xs = []
        for (day, tk), acts in td.items():
            hit = ("BUY" in acts) if key == "BUY" else (acts == {"HOLD"})
            r = px.fwd(tk, day, H)
            if hit and r is not None:
                xs.append(r)
        print(line(label, xs))


def sec_paired(decs: list[dict], px: Prices, H: int) -> None:
    print(f"\n[5] 같은 날끼리 짝지어 비교 + 유의성 검정 — d{H}")
    print("    날짜        BUY평균  HOLD평균   차이   유니버스평균")
    per = defaultdict(lambda: defaultdict(list))
    uni = defaultdict(list)
    tickers = sorted({d["ticker"] for d in decs})
    for d in decs:
        r = px.fwd(d["ticker"], d["ts"][:10], H)
        if r is not None:
            per[d["ts"][:10]][d["action"]].append(r)
    for day in per:
        uni[day] = [r for tk in tickers if (r := px.fwd(tk, day, H)) is not None]
    diffs, wins = [], 0
    for day in sorted(per):
        b, h = per[day]["BUY"], per[day]["HOLD"]
        if not b or not h:
            print(f"    {day}   {pct(mean(b))}  {pct(mean(h))}      -    {pct(mean(uni[day]))}")
            continue
        diff = mean(b) - mean(h)
        diffs.append(diff)
        wins += diff > 0
        print(f"    {day}   {pct(mean(b))}  {pct(mean(h))}  {diff:+6.2f}  {pct(mean(uni[day]))}")
    if not diffs:
        return
    print(f"    BUY가 이긴 날 {wins}/{len(diffs)}일.")
    allb, allh = split(decs, px, H)
    print("\n    유의성 — 무엇을 유효 표본으로 세느냐가 결론을 바꾼다:")
    print(f"      날짜 클러스터(짝지은 차이, 옳은 셈): {ttest1(diffs)}")
    print(f"      관측 단위 Welch(클러스터 무시, 과신): {ttest2(allb, allh)}")
    print(f"      실제 자유도는 관측 {len(allb)+len(allh)}건이 아니라 날짜 {len(diffs)}개 수준이다.")
    print(f"      같은 반도체 복합체 종목 {len(tickers)}개가 강하게 상관돼 종목 축도 독립이 아니다.")


def sec_excess(decs: list[dict], px: Prices, H: int, bench: str | None) -> None:
    print(f"\n[6] 벤치마크 대비 초과수익 — d{H}")
    tickers = sorted({d["ticker"] for d in decs})
    days = {d["ts"][:10] for d in decs}
    for name, getter in (
        (f"{bench}(독립 벤치마크)", (lambda day: px.fwd(bench, day, H)) if bench else None),
        ("유니버스 등가중(비독립)",
         lambda day: mean([r for tk in tickers if (r := px.fwd(tk, day, H)) is not None])),
    ):
        if getter is None:
            continue
        mkt = {day: getter(day) for day in days}
        print(f"    벤치마크 = {name}")
        for act in ("BUY", "HOLD", "SELL"):
            xs = [r - mkt[day] for d in decs if d["action"] == act
                  and (day := d["ts"][:10]) and mkt.get(day) is not None
                  and (r := px.fwd(d["ticker"], day, H)) is not None]
            print(line(f"  {act} 초과수익", xs))

    # 유니버스 벤치마크는 평가 대상 자신을 크게 포함한다 = 같은 사실의 재진술.
    ov = []
    for day in days:
        act_tk = {d["ticker"] for d in decs if d["ts"][:10] == day and d["action"] in ("BUY", "HOLD")}
        live = [tk for tk in tickers if px.fwd(tk, day, H) is not None]
        if live:
            ov.append(100 * len([tk for tk in live if tk in act_tk]) / len(live))
    if ov:
        print(f"    ! 유니버스 벤치마크 구성 종목의 평균 {mean(ov):.0f}%가 그날 평가 대상(BUY/HOLD) 자신이다.")
        print("      이 초과수익은 'BUY<HOLD'의 독립 증거가 아니라 재진술에 가깝다. 같은 사실을 두 번 세지 마라.")


def sec_ticker(decs: list[dict], px: Prices, H: int) -> None:
    print(f"\n[7] 종목별 분해 — 어느 종목이 격차를 만들었나 (d{H})")
    print("    종목     BUY n  BUY평균   HOLD n  HOLD평균    차이   격차기여")
    per = defaultdict(lambda: defaultdict(list))
    for d in decs:
        r = px.fwd(d["ticker"], d["ts"][:10], H)
        if r is not None:
            per[d["ticker"]][d["action"]].append(r)
    nb = sum(len(v["BUY"]) for v in per.values())
    nh = sum(len(v["HOLD"]) for v in per.values())
    rows = []
    for tk, a in per.items():
        b, h = a["BUY"], a["HOLD"]
        # 이 종목이 전체 BUY평균-HOLD평균 격차를 몇 pp 움직였는지
        contrib = (sum(b) / nb if nb else 0) - (sum(h) / nh if nh else 0)
        rows.append((contrib, tk, b, h))
    rows.sort()
    for contrib, tk, b, h in rows:
        d = f"{mean(b) - mean(h):+6.2f}" if b and h else "     -"
        print(f"    {tk}   {len(b):4}  {pct(mean(b))}     {len(h):4}  {pct(mean(h))}  {d}  {contrib:+6.2f}pp")

    # 격차가 종목 두어 개에 얹혀 있으면 '전략의 문제'가 아니라 '표본의 문제'다. 빼보고 확인한다.
    def gap(excl: set[str]) -> str:
        b = [r for tk, a in per.items() if tk not in excl for r in a["BUY"]]
        h = [r for tk, a in per.items() if tk not in excl for r in a["HOLD"]]
        if not b or not h:
            return "n/a"
        return f"{mean(b) - mean(h):+.2f}pp (BUY n={len(b)} {mean(b):+.2f} / HOLD n={len(h)} {mean(h):+.2f})"

    print(f"    전체 격차                : {gap(set())}")
    for k in (1, 2, 3):
        worst = {tk for _, tk, _, _ in rows[:k]}
        print(f"    최악 {k}종목 제외 {','.join(sorted(worst)):<22}: {gap(worst)}")


def sec_momentum(decs: list[dict], px: Prices, H: int) -> None:
    print(f"\n[8] '이미 오른 종목을 사는가' — 판단 직전 5거래일(종점=전일 종가) 수익률")
    for act in ("BUY", "HOLD", "SELL"):
        xs = [r for d in decs if d["action"] == act
              and (r := px.back(d["ticker"], d["ts"][:10], 5)) is not None]
        print(line(f"{act} 직전5일", xs))
    # 종점을 판단일 종가로 두면(=이전 판 코드) 10:30 판단에 5시간 뒤 값이 섞여 결론이 뒤집힌다.
    print("    참고(선견편향 버전, 종점=판단일 종가 — 쓰면 안 되는 값):")
    for act in ("BUY", "HOLD"):
        xs = [r for d in decs if d["action"] == act
              and (r := px.ret(d["ticker"], d["ts"][:10], -5, 0)) is not None]
        print(line(f"  {act} 직전5일(오염)", xs))
    print("    → 두 줄의 대소가 뒤집히면 '추격매수'는 메커니즘이 아니라 측정 산물이다.")

    print(f"\n    직전 5일 성과 구간별 이후 d{H} 수익률:")
    print("    구간              BUY n  BUY평균   HOLD n  HOLD평균")
    buckets = [("급락 <-8%", -1e9, -8), ("약세 -8~-3%", -8, -3), ("보합 -3~+3%", -3, 3),
               ("강세 +3~+10%", 3, 10), ("급등 >+10%", 10, 1e9)]
    for name, lo, hi in buckets:
        out = {}
        for act in ("BUY", "HOLD"):
            xs = []
            for d in decs:
                if d["action"] != act:
                    continue
                day = d["ts"][:10]
                p, f = px.back(d["ticker"], day, 5), px.fwd(d["ticker"], day, H)
                if p is not None and f is not None and lo <= p < hi:
                    xs.append(f)
            out[act] = xs
        b, h = out["BUY"], out["HOLD"]
        print(f"    {name:<16} {len(b):5}  {pct(mean(b))}    {len(h):5}  {pct(mean(h))}")
    print("    (칸당 n이 한 자릿수인 곳이 많다. 구간별 대소는 검정 대상이 아니라 눈요기다.)")


def sec_signals(decs: list[dict], px: Prices, H: int) -> None:
    print(f"\n[9] 판단 근거(reason_summary) 키워드별 이후 d{H} 수익률")
    print("    근거          BUY n  BUY평균   HOLD n  HOLD평균")
    for sig, kws in SIGNAL_KEYWORDS.items():
        out = {}
        for act in ("BUY", "HOLD"):
            xs = []
            for d in decs:
                txt = d.get("reason_summary") or ""
                if d["action"] != act or not any(k in txt for k in kws):
                    continue
                r = px.fwd(d["ticker"], d["ts"][:10], H)
                if r is not None:
                    xs.append(r)
            out[act] = xs
        b, h = out["BUY"], out["HOLD"]
        print(f"    {sig:<12} {len(b):5}  {pct(mean(b))}    {len(h):5}  {pct(mean(h))}")
    print("    (키워드 매칭이라 한 판단이 여러 근거에 중복 계상된다. 대략적 경향만 본다.)")


def load_fills(tdb: Turso, px: Prices, H: int) -> list[dict]:
    """실제 체결 + 체결가 기준 d{H} 수익률. 세 번째 기준가라 [1]과 [10]이 같이 쓴다."""
    rows = tdb.query(
        "SELECT o.id, o.ticker, o.side, o.qty, o.status, o.ordered_at, e.price "
        "FROM orders o LEFT JOIN executions e ON e.order_id = o.id "
        "WHERE o.owner_type = 'ACCOUNT' ORDER BY o.ordered_at"
    )
    out = []
    for r in rows:
        day, tk, p = str(r["ordered_at"])[:10], str(r["ticker"]), r["price"]
        exitp = px.price(tk, day, H)
        # SELL은 체결가 대비 상승이 이익이 아니라 손해라 같은 부호로 섞을 수 없다.
        buy = r["side"] == "BUY"
        out.append({**r, "ticker": tk, "day": day, "close": px.close(tk, day),
                    "ret": (exitp / p - 1) * 100 if buy and p and exitp else None})
    return out


def sec_exec(tdb: Turso, px: Prices, H: int, fills: list[dict]) -> None:
    print("\n[10] 체결 — 체결가와 당일 종가 차이, 실제 실행된 BUY의 모집단")
    if not fills:
        print("    ACCOUNT 주문 없음")
        return
    print("    주문시각            종목    구분  수량   체결가   당일종가   체결가-종가  체결가기준d%d" % H)
    gaps = []
    for r in fills:
        p, c = r["price"], r["close"]
        g = (p / c - 1) * 100 if p and c else None
        if g is not None:
            gaps.append(g)
        print(f"    {r['ordered_at']}   {r['ticker']}  {r['side']:<4} {r['qty']:4}  "
              f"{p if p else '-':>8}  {int(c) if c else '-':>8}   {pct(g)}     {pct(r['ret'])}")
    if gaps:
        print(f"    → 체결가는 당일 종가 대비 평균 {mean(gaps):+.2f}% (양수면 종가보다 비싸게 샀다는 뜻).")
        print("      ret_d5의 기준가는 '당일 종가'라, 이 차이만큼 실현 손익과 지표가 어긋난다.")
    # 하루 3회 판단이라 건수를 그대로 비교하면 과장된다. 종목·날 단위로 맞춰 센다.
    n_dec = tdb.query(
        "SELECT COUNT(*) c FROM (SELECT DISTINCT substr(ts,1,10), ticker "
        "FROM ai_decisions WHERE action='BUY' AND COALESCE(reason_summary,'') <> 'smoke')"
    )[0]["c"]
    n_ord = len({(r["day"], r["ticker"]) for r in fills if r["side"] == "BUY"})
    print(f"    BUY 종목·날 {n_dec}건 중 실제 주문된 것 {n_ord}건 ({100*n_ord/n_dec:.0f}%) — "
          "지표가 재는 BUY와 계좌가 실행한 BUY는 다른 모집단이다.")
    missing = [r["id"] for r in fills if r["status"] == "FILLED" and r["price"] is None]
    if missing:
        print(f"    ! FILLED인데 executions 행이 없는 주문: {missing} (체결 기록 누락)")


# ---------------------------------------------------------------- main


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    p = argparse.ArgumentParser(description="BUY vs HOLD 성과 진단 (읽기 전용)")
    p.add_argument("--from", dest="frm", default="2000-01-01", help="시작일 YYYY-MM-DD")
    p.add_argument("--to", default="9999-12-31", help="종료일 YYYY-MM-DD (판단일 기준, 포함)")
    p.add_argument("--horizon", type=int, default=5, help="보유 거래일 수 (기본 5)")
    p.add_argument("--base", choices=list(BASES), default="close",
                   help="진입가 기준: close=판단일 종가(daily.py ret_d5와 동일), prev=전일 종가")
    p.add_argument("--bench", default="KOSPI", help="독립 벤치마크 지수 코드 (indices.code)")
    a = p.parse_args()

    tdb, mdb = Turso.from_env("TRADING"), Turso.from_env("KRX_MARKET")
    if tdb is None or mdb is None:
        print("TURSO_* env 미설정", file=sys.stderr)
        return 1

    decs = tdb.query(
        "SELECT ticker, ts, action, reason_summary, ret_d5 FROM ai_decisions "
        "WHERE substr(ts,1,10) BETWEEN ? AND ? ORDER BY ts",
        (a.frm, a.to),
    )
    decs = [{**d, "ticker": str(d["ticker"]), "ts": str(d["ts"])} for d in decs]
    # 스모크 테스트 행은 프로덕션 판단이 아니다. 07-31 BUY 표본이 이 한 행뿐이라 남겨두면
    # 헤드라인 격차가 한 행 때문에 0.2pp 넘게 움직인다.
    smoke = [d for d in decs if (d["reason_summary"] or "") == "smoke"]
    decs = [d for d in decs if (d["reason_summary"] or "") != "smoke"]
    if not decs:
        print("해당 기간 판단 없음")
        return 1

    days = [d["ts"][:10] for d in decs]
    tickers = sorted({d["ticker"] for d in decs})
    px = Prices(mdb, tickers, since=f"{min(days)[:4]}-01-01")
    px.base = BASES[a.base][0]
    bench = a.bench if px.add_index(mdb, a.bench, f"{min(days)[:4]}-01-01") else None

    print(f"기간 {min(days)} ~ {max(days)} / 판단 {len(decs)}건 / 종목 {len(tickers)}개 / "
          f"지평선 d{a.horizon} / 진입가 {BASES[a.base][1]}")
    if bench is None:
        print(f"! indices에 {a.bench} 없음 — 독립 벤치마크 생략")
    if smoke:
        print(f"! 스모크 행 {len(smoke)}건 제외: "
              + ", ".join(f"{d['ts']} {d['ticker']} {d['action']}" for d in smoke))
    counts = defaultdict(int)
    for d in decs:
        counts[d["action"]] += 1
    print("액션 분포: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))

    fills = load_fills(tdb, px, a.horizon)
    sec_sensitivity(decs, px, a.horizon, fills)
    sec_coverage(decs, a.horizon)
    sec_naive(decs, px, a.horizon)
    sec_tickerday(decs, px, a.horizon)
    sec_paired(decs, px, a.horizon)
    sec_excess(decs, px, a.horizon, bench)
    sec_ticker(decs, px, a.horizon)
    sec_momentum(decs, px, a.horizon)
    sec_signals(decs, px, a.horizon)
    sec_exec(tdb, px, a.horizon, fills)
    return 0


def _selfcheck() -> None:
    """수익률이 거래일 인덱스 기준으로 맞는지 + 직전 N일에 미래 값이 안 섞이는지 + t검정."""
    p = Prices.__new__(Prices)
    p.base = 0
    p.px = {"X": (["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"],
                  [100.0, 110.0, 90.0, 120.0])}
    assert abs(p.fwd("X", "2026-08-03", 1) - 10.0) < 1e-9
    assert abs(p.fwd("X", "2026-08-03", 3) - 20.0) < 1e-9
    assert p.fwd("X", "2026-08-03", 5) is None              # 데이터 부족은 조용히 제외
    assert abs(p.fwd("X", "2026-08-01", 1) - 10.0) < 1e-9   # 휴장일 판단은 다음 거래일 기준
    # 진입가를 전일 종가로 바꾸면 판단 당일 등락만큼 결과가 달라진다
    p.base = -1
    assert abs(p.fwd("X", "2026-08-05", 1) - 9.0909090909) < 1e-6   # 110 → 120
    p.base = 0
    assert abs(p.fwd("X", "2026-08-05", 1) - 33.3333333333) < 1e-6  # 90 → 120
    # 핵심: 08-05 판단의 '직전 1일'은 08-03→08-04이지 08-04→08-05가 아니다(미래 금지)
    assert abs(p.back("X", "2026-08-05", 1) - 10.0) < 1e-9
    assert p.back("X", "2026-08-04", 2) is None             # 과거 부족도 조용히 제외
    assert abs(p.ret("X", "2026-08-05", -1, 0) + 18.1818181818) < 1e-6  # 당일 등락 110→90
    assert p.close("X", "2026-08-04") == 110
    assert p.close("X", "2026-08-01") is None
    assert p.price("X", "2026-08-05", 1) == 120
    # t분포: df=4에서 |t|=2.776이 정확히 양측 5%
    assert abs(t_p(2.776445, 4) - 0.05) < 1e-4
    assert abs(t_p(1.959964, 1e7) - 0.05) < 1e-3
    assert "t=+3.87 df=3 p=0.030" in ttest1([1.0, 2.0, 3.0, 4.0])  # 평균2.5 sd1.291
    print("selfcheck ok")


if __name__ == "__main__":
    sys.exit(_selfcheck() or 0 if "--selfcheck" in sys.argv else main())
