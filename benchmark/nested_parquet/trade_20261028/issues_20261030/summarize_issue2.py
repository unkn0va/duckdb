#!/usr/bin/env python3
"""The tables of issue 2 from a run_issue2.sh folder, as markdown on stdout.

  2-1  variants.csv: the original query, the fixed join order and the aggregation before the dimension join, per
       configuration - seconds, ratio to the original, result equal to the original
  2-2  cardinality.csv: how many joins / UNNESTs / scans were recorded per dataset and configuration
  2-3  the distribution of the q-error (median, 90th percentile, maximum, share of underestimates) per method,
       configuration and kind of join; the input scans; and what the estimate of a child node scan of read_parquet_flat
       is compared with the parquet metadata (num_values) and the actual rows

Usage: summarize_issue2.py <run_issue2.sh output folder>
"""
import collections
import csv
import math
import os
import statistics
import sys

OUT = sys.argv[1] if __name__ == "__main__" else ""
CONFIGS = ["base", "prenestoff", "prenest", "flat", "pureflat"]
FORMS = ["orig", "fixed", "preagg"]


def variants():
    path = os.path.join(OUT, "variants.csv")
    if not os.path.exists(path):
        return
    rows = {(r["name"], r["config"]): r for r in csv.DictReader(open(path))}
    queries = list(dict.fromkeys(name.split(".")[0] for name, _ in rows))
    print("## 2-1 실행 계획 변형 (1스레드, RUNS 중 최소, 초)\n")
    print("- fixed: `join_order`를 끄고 원소 → 부모 → 차원 표 순서로 씀(build 쪽은 build_side_probe_side가 정함). builtin·flat은 글이 같고 설정만 다름.")
    print("- preagg: 차원 표 join 앞에서 집계(q7_csa: c0, c1별 / q7_plots: c8별). q1, q6은 차원 표 join이 없어 해당 없음.")
    print("- 괄호: 원래 대비 배수(< 1이면 빠름). '=': 원래와 같은 실행 계획이라 다시 재지 않음. 결과: 모든 변형이 원래 쿼리(base builtin)와 같으면 yes.")
    print("- 계획: `variant_plans/<쿼리>.<변형>.<구성>.txt`\n")
    print("| 쿼리 | 구성 | orig | fixed | preagg | 결과 |\n|---|---|---|---|---|---|")
    for q in queries:
        for config in CONFIGS:
            orig = rows.get((f"{q}.orig", config))
            if not orig:
                continue
            cells, same = [], []
            for form in FORMS:
                row = rows.get((f"{q}.{form}", config))
                if not row:
                    cells.append("·")
                    continue
                same.append(row["same_result"])
                if not row["wall_s"]:
                    cells.append(f"오류: {row['note'][:40]}")
                elif form == "orig":
                    cells.append(row["wall_s"])
                elif row["note"].startswith("same plan"):
                    cells.append("=")
                else:
                    ratio = float(row["wall_s"]) / float(orig["wall_s"]) if orig["wall_s"] else math.nan
                    cells.append(f"{row['wall_s']} ({ratio:.2f})")
            result = "yes" if all(s == "yes" for s in same) else "NO"
            print(f"| {q} | {config} | " + " | ".join(cells) + f" | {result} |")
    print()


def load_cardinality():
    path = os.path.join(OUT, "cardinality.csv")
    return list(csv.DictReader(open(path))) if os.path.exists(path) else []


def quantile(values, q):
    values = sorted(values)
    if not values:
        return math.nan
    pos = (len(values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def distribution(rows):
    errors = [float(r["q_error"]) for r in rows if r["q_error"]]
    under = sum(1 for r in rows if r["q_error"] and r["est"] and int(r["est"]) < int(r["actual"]))
    if not errors:
        return "| 0 | · | · | · | · |"
    return (f"| {len(errors)} | {statistics.median(errors):.2f} | {quantile(errors, 0.9):.2f} | {max(errors):.1f} | "
            f"{100 * under / len(errors):.0f}% |")


def cardinality_tables(rows):
    if not rows:
        return
    errors = [r for r in rows if r["error"]]
    joins = [r for r in rows if not r["error"] and r["kind"] not in ("scan", "")]
    scans = [r for r in rows if not r["error"] and r["kind"] == "scan"]
    print("## 2-2 예상 행 수 vs 실제 행 수\n")
    print("전체 기록은 `cardinality.csv`(join, UNNEST, 그 입력 스캔마다 한 행: est, actual, q_error, 종류, 동적 필터 여부, flat 노드의 num_values).\n")
    print("| 데이터 | 쿼리 수 | join·UNNEST 행 | 스캔 행 | 오류 |\n|---|---|---|---|---|")
    datasets = list(dict.fromkeys(r["dataset"] for r in rows))
    for d in datasets:
        print(f"| {d} | {len({r['query'] for r in rows if r['dataset'] == d})} | "
              f"{sum(1 for r in joins if r['dataset'] == d)} | {sum(1 for r in scans if r['dataset'] == d)} | "
              f"{sum(1 for r in errors if r['dataset'] == d)} |")
    print()
    for r in errors[:20]:
        print(f"- 오류: {r['dataset']} {r['query']} {r['config']}: {r['error']}")
    if errors:
        print()

    print("## 2-3 요약\n")
    print("q-error = max(예상/실제, 실제/예상). 과소추정 = 예상 < 실제인 비율.")
    print("방식 A = base / prenestoff / prenest(builtin), 방식 B = flat / pure flat. A의 '중첩: UNNEST'가 B의 '중첩: parent-child' join에 해당합니다.")
    print("UNNEST는 자기 예상이 없어 입력의 예상을 그대로 씁니다(`src/planner/logical_operator.cpp:261-272`, 리스트 길이 1로 보는 셈).\n")
    for title, subset in (("trade (40개 쿼리)", [r for r in joins if r["dataset"] == "trade"]),
                          ("지난 데이터 (TPC-H, XMark, DBLP, selectivity)", [r for r in joins if r["dataset"] != "trade"]),
                          ("전체", joins)):
        if not subset:
            continue
        print(f"### join·UNNEST의 q-error: {title}\n")
        print("| 방식 | 구성 | 종류 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |\n|---|---|---|---|---|---|---|---|")
        groups = collections.defaultdict(list)
        for r in subset:
            groups[(r["method"], r["config"], r["kind"])].append(r)
        for (method, config, kind), group in sorted(groups.items(), key=lambda kv: (kv[0][0], CONFIGS.index(kv[0][1]), kv[0][2])):
            print(f"| {method} | {config} | {kind} " + distribution(group))
        print()
        print("방식별로 묶은 것 (구성 구분 없음):\n")
        print("| 방식 | 종류 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |\n|---|---|---|---|---|---|---|")
        groups = collections.defaultdict(list)
        for r in subset:
            groups[(r["method"], "nesting" if r["kind"].startswith("nesting") else "regular")].append(r)
        for (method, kind), group in sorted(groups.items()):
            print(f"| {method} | {kind} " + distribution(group))
        print()

    print("### 입력 스캔의 q-error\n")
    print("스캔의 실제 행은 필터 뒤, 그리고 동적 join 필터 뒤의 값입니다. 동적 필터가 있는 스캔은 예상이 그것을 모르므로 따로 셉니다.\n")
    print("| 방식 | 구성 | 스캔 | 개수 | 중앙값 | 90% | 최댓값 | 과소추정 |\n|---|---|---|---|---|---|---|---|")
    groups = collections.defaultdict(list)
    for r in scans:
        kind = "동적 필터" if r["dynamic_filters"] else "필터" if r["filters"] else "필터 없음"
        groups[(r["method"], r["config"], kind)].append(r)
    for (method, config, kind), group in sorted(groups.items(), key=lambda kv: (kv[0][0], CONFIGS.index(kv[0][1]), kv[0][2])):
        print(f"| {method} | {config} | {kind} " + distribution(group))
    print()

    nodes = [r for r in scans if r["nv_first"] and "node: (top level)" not in r["detail"]]
    print("### flat 자식 노드 스캔의 예상 vs parquet num_values\n")
    print("`read_parquet_node`의 예상 = 노드 첫 leaf의 row group별 `num_values` 합(`extension/parquet/parquet_node_scan.cpp:186-191`).")
    print("num_values는 빈 리스트·NULL 리스트의 자리(placeholder)도 세므로, 그런 것이 있으면 실제 원소 수보다 큽니다.\n")
    if not nodes:
        print("기록 없음.\n")
        return
    relations = collections.Counter(r["nv_relation"].split(" x ")[0] + (" x f (필터)" if " x " in r["nv_relation"] else "")
                                    for r in nodes)
    print("| 관계 | 스캔 수 |\n|---|---|")
    for relation, n in relations.most_common():
        print(f"| {relation} | {n} |")
    print()
    print("노드마다: num_values(첫 leaf)와 노드의 실제 행 수(빈·NULL 리스트 자리를 뺀 `read_parquet_node` 행 수)\n")
    print("| 데이터 | 파일 | 노드 | num_values (첫 leaf / 노드의 leaf들) | 노드 행 | num_values / 노드 행 | 쿼리에서 본 관계 |")
    print("|---|---|---|---|---|---|---|")
    by_node = collections.defaultdict(list)
    for r in nodes:
        file = r["detail"].split("file: ")[1].split(";")[0]
        node = r["detail"].split("node: ")[1].split(";")[0]
        by_node[(r["dataset"], file, node)].append(r)
    for (dataset, file, node), group in by_node.items():
        r = group[0]
        rows_ = int(r["node_rows"]) if r["node_rows"] else None
        ratio = f"{int(r['nv_first']) / rows_:.4f}" if rows_ else "·"
        seen = ", ".join(sorted({g["nv_relation"].replace(" (filter)", "") for g in group}))
        print(f"| {dataset} | {file} | {node} | {int(r['nv_first']):,} / {r['nv_leaves']} | "
              f"{rows_:,} | {ratio} | {seen} |" if rows_ else f"| {dataset} | {file} | {node} | {r['nv_first']} | · | · | {seen} |")
    print()


def main():
    print(f"# 이슈 2: join 예상 오류 ({os.path.basename(os.path.abspath(OUT))})\n")
    info = os.path.join(OUT, "run_info.txt")
    if os.path.exists(info):
        print("```\n" + open(info).read().strip() + "\n```\n")
    variants()
    cardinality_tables(load_cardinality())


if __name__ == "__main__":
    main()
