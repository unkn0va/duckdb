#!/usr/bin/env python3
"""The data of the presentation figures (follow-up E) as CSV files in <results>/figures/, with a README that names
the experiment and file every one comes from. Column names are Korean with the English word in brackets.

  fig1_category_shares.csv     issue 1: share of every category (new basis) per query and configuration
  fig2_stage_vs_perf.csv       issue 1: stage queries, measured time difference vs perf category differences
  fig3_qerror.csv              issue 2: q-error of every join / UNNEST, method and kind
  fig4_q7_variants.csv         issue 2: q7_csa, q7_plots - original / fixed join order / aggregation first
  fig5_fanout.csv              issue 2: follow-up D, time per k, storage, configuration, variant (when present)
  fig6_overhead_composition.csv  both: per query, the parts of the unnest overhead (A) and of the join overhead (B)

Usage: make_figures.py <results folder: server_20261030> [<folder with fanout.csv>]
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from categories import CATEGORIES  # noqa: E402
from summarize_extra import runs_of  # noqa: E402

CONFIGS = ["base", "prenestoff", "prenest", "flat", "pureflat"]
STAGES = ["s1_box", "s2_unnest", "s2f_fields", "s3_cond"]
README = []


def write(folder, name, header, rows, source):
    with open(os.path.join(folder, name), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    README.append(f"| `{name}` | {len(rows)} | {source} |")


def ordered(runs):
    return sorted(runs.items(), key=lambda kv: (kv[0][0], CONFIGS.index(kv[0][1]) if kv[0][1] in CONFIGS else 9))


def main():
    results = os.path.abspath(sys.argv[1])
    out = os.path.join(results, "figures")
    os.makedirs(out, exist_ok=True)
    i1, i1c, i2 = (os.path.join(results, d) for d in ("issue1", "issue1c", "issue2"))

    rows = []
    for folder, label in ((f"{i1}/profile/params", ""), (f"{i1}/profile/tpch_sf1", "TPC-H SF1 "),
                          (f"{i1}/profile/tpch_sf10", "TPC-H SF10 "), (f"{i1c}/profile/params", "")):
        for (query, config), run in ordered(runs_of(folder)):
            for category in CATEGORIES:
                rows.append([label + query, config, category, f"{run[category]:.3f}",
                             f"{100 * run[category] / run['cpu']:.2f}", f"{run['cpu']:.3f}"])
    write(out, "fig1_category_shares.csv",
          ["쿼리 (query)", "구성 (config)", "범주 (category, 새 기준)", "CPU 초 (cpu_s)", "비율 % (share_pct)",
           "실행 CPU 초 (run_cpu_s)"], rows,
          "issue1/profile/{params,tpch_sf1,tpch_sf10}/*.folded.gz, issue1c/profile/params/*.folded.gz "
          "(categories.py로 다시 분류)")

    times = {(r["name"], r["config"]): float(r["wall_s"]) for r in csv.DictReader(open(f"{i1}/stage_time.csv"))
             if r["wall_s"]}
    perf = runs_of(f"{i1}/profile/stage")
    rows = []
    for config in CONFIGS:
        for a, b in zip(STAGES, STAGES[1:]):
            if (a, config) not in perf or (b, config) not in perf:
                continue
            step = f"{a.split('_')[0]}→{b.split('_')[0]}"
            rows.append([config, step, "측정 시간 차이 (wall)", f"{times[(b, config)] - times[(a, config)]:.3f}"])
            rows.append([config, step, "perf CPU 차이 (cpu)", f"{perf[(b, config)]['cpu'] - perf[(a, config)]['cpu']:.3f}"])
            for category in CATEGORIES:
                rows.append([config, step, category, f"{perf[(b, config)][category] - perf[(a, config)][category]:.3f}"])
    write(out, "fig2_stage_vs_perf.csv",
          ["구성 (config)", "단계 전환 (step)", "항목 (item: 시간 차이 또는 perf 범주)", "차이 초 (delta_s)"], rows,
          "issue1/stage_time.csv (RUNS=10 중 최소), issue1/profile/stage/*.folded.gz")

    rows = []
    for r in csv.DictReader(open(f"{i2}/cardinality.csv")):
        if r["error"] or r["kind"] in ("scan", "") or not r["q_error"]:
            continue
        kind = ("UNNEST" if r["kind"] == "nesting: UNNEST" else "부모⋈자식 (parent-child)"
                if r["kind"].startswith("nesting: parent-child") else "형제 (sibling)"
                if r["kind"].startswith("nesting") else "일반 (regular)")
        rows.append([r["dataset"], r["query"], r["config"], r["method"], kind, r["est"], r["actual"], r["q_error"]])
    write(out, "fig3_qerror.csv",
          ["데이터 (dataset)", "쿼리 (query)", "구성 (config)", "방식 (method: A nested, B flat)", "join 종류 (kind)",
           "예상 행 (est)", "실제 행 (actual)", "오차 배수 (q_error)"], rows, "issue2/cardinality.csv (join과 UNNEST 행만)")

    rows = []
    variants = {(r["name"], r["config"]): r for r in csv.DictReader(open(f"{i2}/variants.csv"))}
    for q in ("q7_csa", "q7_plots"):
        for config in CONFIGS:
            orig = variants.get((f"{q}.orig", config))
            for form, label in (("orig", "원래"), ("fixed", "join 순서 고정"), ("preagg", "합계 먼저")):
                r = variants.get((f"{q}.{form}", config))
                if not r or not r["wall_s"]:
                    continue
                rows.append([q, config, label, r["wall_s"], f"{float(r['wall_s']) / float(orig['wall_s']):.3f}",
                             "yes" if r["note"].startswith("same plan") else "no", r["same_result"]])
    write(out, "fig4_q7_variants.csv",
          ["쿼리 (query)", "구성 (config)", "변형 (variant)", "시간 초 (wall_s, 10회 중 최소)", "원래 대비 배수 (ratio)",
           "원래와 같은 계획 (same_plan)", "결과 일치 (same_result)"], rows, "issue2/variants.csv")

    fanout = os.path.join(sys.argv[2], "fanout.csv") if len(sys.argv) > 2 else ""
    if fanout and os.path.exists(fanout):
        rows = []
        storages = {"a": "(a) 사실·차원 parquet", "b": "(b) 사실 parquet, 차원 내부 테이블", "c": "(c) 둘 다 내부 테이블"}
        for r in csv.DictReader(open(fanout)):
            storage, rest = r["name"].split("_", 1)
            k, form = rest.split(".")
            rows.append([storages[storage], int(k[1:]), r["config"], "원래" if form == "orig" else "합계 먼저",
                         r["wall_s"], r["plan_flag"], r["same_result"]])
        write(out, "fig5_fanout.csv",
              ["저장 방식 (storage)", "k (시나리오당 날짜 수)", "구성 (config)", "변형 (variant)", "시간 초 (wall_s)",
               "자동 적용 (partial_aggregate_pushdown)", "결과 일치 (same_result)"], rows,
              f"{os.path.relpath(fanout, results)} (후속 D)")

    rows = []
    perf = {**runs_of(f"{i1}/profile/params"), **runs_of(f"{i1c}/profile/params")}
    for q in ("q1_s01", "q1_s50", "q6_group", "q7_csa", "q7_plots"):
        for config, method in (("base", "A"), ("prenest", "A"), ("flat", "B"), ("pureflat", "B")):
            run = perf.get((q, config))
            if not run:
                continue
            parts = ([("리스트 조립", run["리스트 조립"]), ("UNNEST", run["UNNEST"]), ("원소 다루기", run["원소 다루기"])]
                     if method == "A" else [("부모⋈자식 등 hash join", run["join"]), ("키 생성", run["키 생성"]),
                                            ("원소 다루기", run["원소 다루기"])])
            parts += [("값 디코드", run["값 디코드"]), ("집계", run["집계"]), ("기타", run["기타"])]
            for part, seconds in parts:
                rows.append([q, config, method, part, f"{seconds:.3f}", f"{run['wall']:.3f}"])
    write(out, "fig6_overhead_composition.csv",
          ["쿼리 (query)", "구성 (config)", "방식 (method)", "구성 요소 (part)", "CPU 초 (cpu_s)", "실행 시간 초 (wall_s)"],
          rows, "issue1/profile/params (q1_s01, q1_s50), issue1c/profile/params (q6_group, q7_csa, q7_plots), "
          "새 기준 perf 범주; B의 join은 perf join 범주 전체(차원 표 join 포함)")

    with open(os.path.join(out, "README.md"), "w") as f:
        f.write("# 발표용 그래프 데이터\n\n`make_figures.py`가 만듭니다. 시간은 1스레드, 1억 행(TPC-H는 표시한 SF)입니다.\n\n"
                "| 파일 | 행 | 출처 (`server_20261030/` 기준) |\n|---|---|---|\n" + "\n".join(README) + "\n")
    print("\n".join(README))


if __name__ == "__main__":
    main()
