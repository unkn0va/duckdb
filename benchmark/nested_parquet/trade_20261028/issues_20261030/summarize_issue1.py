#!/usr/bin/env python3
"""The tables of issue 1 from a run_issue1.sh folder, as markdown on stdout.

  1-1  stage times (stage_time.csv) next to the perf categories of the same stage queries (profile/stage), and the
       difference from one stage to the next per category
  1-2  perf categories of the parameter queries (profile/params) with their lists and elements (counts.csv); cost
       per list and per element, and which unit keeps it constant across the queries (coefficient of variation)
  1-3  perf categories of TPC-H (profile/tpch_sf1, profile/tpch_sf10)
  1-4  the category rules (categories.py), the runs where "기타" exceeds 10% with its top functions, and the callers
       of the watched functions (string copies, validity) in q2_s50

Usage: summarize_issue1.py <run_issue1.sh output folder>
"""
import collections
import csv
import io
import os
import re
import statistics
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from categories import CATEGORIES, table as category_table  # noqa: E402

OUT = sys.argv[1] if __name__ == "__main__" else ""
CONFIGS = ["base", "prenestoff", "prenest", "flat", "pureflat"]
STAGES = ["s1_box", "s2_unnest", "s2f_fields", "s3_cond"]
SHORT = {"값 디코드": "디코드", "리스트 조립": "조립", "UNNEST": "UNNEST", "원소 다루기": "원소", "키 생성": "키",
         "join": "join", "집계": "집계", "기타": "기타"}


def load_profile(folder):
    """{(query, config): {"wall": s, "cpu": s, category: s, (category, sub): s}}"""
    path = os.path.join(OUT, "profile", folder, "profile.csv")
    runs = collections.defaultdict(lambda: collections.defaultdict(float))
    if not os.path.exists(path):
        return runs
    with open(path) as f:
        rows = list(csv.reader(f))[1:]
    for query, config, wall, cpu, category, sub, ms in rows:
        run = runs[(query, config)]
        run["wall"], run["cpu"] = float(wall) / 1000, float(cpu) / 1000
        run[category] += float(ms) / 1000
        run[(category, sub)] += float(ms) / 1000
    return runs


def fmt(value, digits=2):
    if value is None or value == "":
        return "·"
    if isinstance(value, str):
        return value
    return "·" if abs(value) < 0.5 * 10**-digits else f"{value:.{digits}f}"


def category_header(extra=()):
    cols = [*extra, *(SHORT[c] for c in CATEGORIES)]
    return "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols)


def stage_tables():
    times = {}
    path = os.path.join(OUT, "stage_time.csv")
    if os.path.exists(path):
        for row in csv.DictReader(open(path)):
            times[(row["name"], row["config"])] = row
    perf = load_profile("stage")
    if not times and not perf:
        return
    print("## 1-1 단계 누적 쿼리 (legs, 1스레드)\n")
    print("단계: s1 상자(목록만) → s2 펼치기(count) → s2f 펼치기 + s3에서 쓰는 필드 2개 → s3 q2_c50 조건과 합계.")
    print("flat·pure flat에는 상자가 없어 s1은 키만 읽고, s2와 s2f는 같은 쿼리입니다. 쿼리는 `queries_stage/`, 계획 확인은 `stage_check.md`.\n")
    print("### 시간 (초, RUNS 중 최소) / 결과 일치\n")
    print("| 구성 | " + " | ".join(STAGES) + " |\n|---|" + "---|" * len(STAGES))
    for config in CONFIGS:
        cells = []
        for stage in STAGES:
            row = times.get((stage, config))
            cells.append(f"{row['wall_s'] or row['note']} ({row['same_result']})" if row else "·")
        print(f"| {config} | " + " | ".join(cells) + " |")
    print()
    if not perf:
        return
    print("### perf 범주 (CPU 초)\n")
    print(category_header(("구성", "단계", "wall", "CPU")))
    for config in CONFIGS:
        for stage in STAGES:
            run = perf.get((stage, config))
            if run:
                print(f"| {config} | {stage} | {fmt(run['wall'])} | {fmt(run['cpu'])} | "
                      + " | ".join(fmt(run[c]) for c in CATEGORIES) + " |")
    print()
    print("### 단계 사이의 차이: 측정 시간 차이 vs perf 범주 차이 (초)\n")
    print("Δwall은 stage_time.csv(최소 시간)의 차이, 나머지는 perf 실행 한 번의 범주별 CPU 차이입니다.")
    print("기대: s1→s2는 UNNEST, s2→s2f는 (가지치기하는 구성에서) 디코드·조립 감소 + 필드 꺼내기, s2f→s3는 원소 다루기(조건)와 집계.\n")
    print(category_header(("구성", "단계", "Δwall", "ΔCPU(perf)")))
    for config in CONFIGS:
        for a, b in zip(STAGES, STAGES[1:]):
            ra, rb = perf.get((a, config)), perf.get((b, config))
            ta, tb = times.get((a, config)), times.get((b, config))
            dwall = float(tb["wall_s"]) - float(ta["wall_s"]) if ta and tb and ta["wall_s"] and tb["wall_s"] else None
            if not (ra and rb):
                continue
            print(f"| {config} | {a.split('_')[0]}→{b.split('_')[0]} | {fmt(dwall)} | {fmt(rb['cpu'] - ra['cpu'])} | "
                  + " | ".join(fmt(rb[c] - ra[c]) for c in CATEGORIES) + " |")
    print()


def load_counts():
    path = os.path.join(OUT, "counts.csv")
    return {row["query"]: {k: (int(v) if v.isdigit() else v) for k, v in row.items()} for row in csv.DictReader(open(path))} \
        if os.path.exists(path) else {}


def cv(values):
    values = [v for v in values if v is not None]
    if len(values) < 2 or statistics.mean(values) == 0:
        return None
    return statistics.pstdev(values) / statistics.mean(values)


def param_tables():
    perf = load_profile("params")
    counts = load_counts()
    if not perf:
        return
    queries = list(dict.fromkeys(q for q, _ in perf))
    print("## 1-2 파라미터별 분해 (1스레드, perf)\n")
    if counts:
        print("### 리스트와 원소 수 (base EXPLAIN ANALYZE와 파일)\n")
        print("| 쿼리 | 열 | 리스트 (파일 행) | 원소 (파일) | 스캔이 낸 리스트 | UNNEST 원소 | 통과 원소 |\n|---|---|---|---|---|---|---|")
        for q in queries:
            c = counts.get(q)
            if c:
                print(f"| {q} | {c['column']} | {c['lists_total']:,} | {c['elements_total']:,} | {c['lists_scanned']:,} | "
                      f"{c['elements_unnested']:,} | {c['elements_passing']:,} |")
        print()
    print("### 범주별 CPU 초\n")
    print(category_header(("쿼리", "구성", "wall", "CPU")))
    for q in queries:
        for config in CONFIGS:
            run = perf.get((q, config))
            if run:
                print(f"| {q} | {config} | {fmt(run['wall'])} | {fmt(run['cpu'])} | "
                      + " | ".join(fmt(run[c]) for c in CATEGORIES) + " |")
    print()
    if not counts:
        return
    units = [("lists_total", "파일 리스트"), ("lists_scanned", "스캔한 리스트"), ("elements_total", "파일 원소"),
             ("elements_unnested", "펼친 원소"), ("elements_passing", "통과 원소")]
    print("### 원소당·리스트당 비용 (ns)\n")
    print("범주 시간을 다섯 가지 단위 수로 나눈 값의 평균과, 쿼리 사이의 변동계수 CV(표준편차/평균)입니다.")
    print("비용이 그 단위에 비례하면 단위당 비용이 쿼리마다 같아 CV가 작습니다. 판단 = CV가 가장 작은 단위.")
    print("단위 수는 위 표의 값이고 flat·pure flat에도 같은 수를 씁니다. 0.01초 미만인 칸은 뺍니다.\n")
    print("| 구성 | 범주 | 쿼리 수 | " + " | ".join(f"{label} ns (CV)" for _, label in units) + " | 판단 |")
    print("|---|---|---|" + "---|" * len(units) + "---|")
    for config in CONFIGS:
        for category in ("값 디코드", "리스트 조립", "UNNEST", "원소 다루기", "키 생성", "join", "집계"):
            per_unit = {key: [] for key, _ in units}
            for q in queries:
                run, c = perf.get((q, config)), counts.get(q)
                if not run or not c or run[category] < 0.01:
                    continue
                for key, _ in units:
                    per_unit[key].append(run[category] * 1e9 / c[key])
            n = len(per_unit[units[0][0]])
            if n < 3:
                continue
            cvs = {key: cv(values) for key, values in per_unit.items()}
            best = min(units, key=lambda u: cvs[u[0]])[1]
            print(f"| {config} | {category} | {n} | "
                  + " | ".join(f"{statistics.mean(per_unit[key]):.1f} ({cvs[key]:.2f})" for key, _ in units)
                  + f" | {best} |")
    print()


def tpch_tables():
    rows = []
    for name in ("tpch_sf1", "tpch_sf10"):
        perf = load_profile(name)
        for (q, config), run in perf.items():
            rows.append((name, q, config, run))
    if not rows:
        return
    print("## 1-3 TPC-H (1스레드, perf)\n")
    print("CPU 초, 괄호는 비율(%).\n")
    print(category_header(("데이터", "쿼리", "구성", "wall", "CPU")))
    for name, q, config, run in rows:
        print(f"| {name} | {q} | {config} | {fmt(run['wall'])} | {fmt(run['cpu'])} | "
              + " | ".join(f"{fmt(run[c])} ({100 * run[c] / run['cpu']:.0f})" if run[c] >= 0.005 else "·" for c in CATEGORIES)
              + " |")
    print()


def other_review():
    """Runs with 기타 > 10% of CPU and their top 기타 functions (from the .txt files)."""
    found = []
    for folder in ("stage", "params", "tpch_sf1", "tpch_sf10"):
        perf = load_profile(folder)
        for (q, config), run in perf.items():
            if run["cpu"] and run["기타"] / run["cpu"] > 0.10:
                text = open(os.path.join(OUT, "profile", folder, f"{q}.{config}.txt")).read()
                top = re.findall(r"^  기타\s+(\d+) ms  (.*)$", text, re.M)[:5]
                subs = ", ".join(f"{s} {fmt(v)}" for (c, s), v in sorted(
                    ((k, v) for k, v in run.items() if isinstance(k, tuple) and k[0] == "기타"), key=lambda kv: -kv[1]))
                found.append((folder, q, config, 100 * run["기타"] / run["cpu"], subs, top))
    return found


def watched():
    """The callers of the watched functions in q2_s50 (params) per configuration, from the .txt files."""
    lines = []
    for config in CONFIGS:
        path = os.path.join(OUT, "profile", "params", f"q2_s50.{config}.txt")
        if not os.path.exists(path):
            continue
        text = open(path).read()
        part = text.split("callers of the watched functions", 1)
        if len(part) == 2:
            lines.append(f"**q2_s50 {config}**\n\n```\n" + part[1].split("\n", 1)[1].rstrip() + "\n```\n")
    return lines


def categories_section():
    print("## 1-4 범주 정의\n")
    print("perf 샘플마다 호출 스택을 잎(샘플된 함수)에서 위로 따라가며, 아래 규칙에 처음 맞는 함수가 범주를 정합니다.")
    print("규칙에 없는 함수(memcpy·malloc, kernel, validity·벡터 도우미, 해시, tuple data, 문자열 연산)는 건너뛰고, 그것을 부른 코드의 범주를 받습니다.")
    print("'임시' 규칙(식 평가)은 위쪽에서 연산자(FILTER, PROJECTION, 스캔 필터, prenest, join, 집계)를 만나면 그 연산자를 따릅니다.")
    print("함수 이름은 인자를 뺀 이름으로 맞춥니다. 원본 스택은 `profile/*/*.folded.gz`에 있어 `categories.py classify`로 다시 나눌 수 있습니다.\n")
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        category_table()
    print(buffer.getvalue())
    found = other_review()
    print("### '기타'가 10%를 넘는 실행\n")
    if not found:
        print("없음.\n")
    for folder, q, config, share, subs, top in found:
        print(f"- {folder} {q} {config}: 기타 {share:.0f}% ({subs})")
        for ms, function in top:
            print(f"  - {ms} ms `{function[:120]}`")
    print()
    lines = watched()
    if lines:
        print("### 문자열 복사·validity 함수를 부른 곳 (q2_s50)\n")
        print("범주/세부, 그리고 그 함수 위의 세 프레임.\n")
        print("\n".join(lines))


def main():
    print(f"# 이슈 1: Unnest 오버헤드 분해 ({os.path.basename(os.path.abspath(OUT))})\n")
    info = os.path.join(OUT, "run_info.txt")
    if os.path.exists(info):
        print("```\n" + open(info).read().strip() + "\n```\n")
    stage_tables()
    param_tables()
    tpch_tables()
    categories_section()


if __name__ == "__main__":
    main()
