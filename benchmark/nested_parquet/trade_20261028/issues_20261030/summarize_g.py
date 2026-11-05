#!/usr/bin/env python3
"""The tables of follow-ups G1-G4 from a run_followup2.sh folder, as markdown on stdout.

  G1  branch mispredictions: per q2_c point and configuration the Bad Speculation share of the slots, the cycles it
      stands for (share x cycles), the branch misses and the cycles per miss; and q2_c50 on trade_B vs trade_Bsorted
      (same rows in leg_id order): time, the perf category "원소 다루기", branch misses
  G2  q4_two, larger vs smaller list built: perf categories and the phases of the hash join (categories.join_phase),
      page faults and maximum RSS
  G3  k = 4, aggregation first, parquet (a) vs DuckDB tables (c): perf categories; stage queries on both: time
  G4  synthetic lists of length L: time and perf categories against L, a straight line (per list + per element), R²

Usage: summarize_g.py <run_followup2.sh output folder>
"""
import collections
import csv
import glob
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from categories import CATEGORIES, classify_samples, join_phase, read_folded  # noqa: E402

OUT = sys.argv[1] if __name__ == "__main__" else ""
SHORT = {"값 디코드": "디코드", "리스트 조립": "조립", "UNNEST": "UNNEST", "원소 다루기": "원소", "키 생성": "키",
         "join": "join", "집계": "집계", "기타": "기타"}
Q2C = ["q2_c01", "q2_c10", "q2_c25", "q2_c50", "q2_c75"]
PASS = {"q2_c01": "0.9%", "q2_c10": "10%", "q2_c25": "25%", "q2_c50": "50%", "q2_c75": "75%"}
CONFIGS = ["base", "prenestoff", "prenest", "flat", "pureflat"]


def path(*parts):
    return os.path.join(OUT, *parts)


def stat(name):
    """{(query, config): {item: value}} of a perf_stat.py CSV."""
    result = collections.defaultdict(dict)
    if os.path.exists(path(name)):
        for r in csv.DictReader(open(path(name))):
            try:
                result[(r["name"], r["config"])][r["item"]] = float(r["value"])
            except ValueError:  # "<not supported>", or the message of an error row
                if r["item"] == "error":
                    result[(r["name"], r["config"])]["error"] = r["value"]
            if r["wall_s"]:
                result[(r["name"], r["config"])]["wall"] = float(r["wall_s"])
    return result


def times(name):
    return {(r["name"], r["config"]): r for r in csv.DictReader(open(path(name)))} if os.path.exists(path(name)) else {}


def profiles(folder):
    """{(query, config): {"cpu", "wall", category: s, ("phase", phase): s, ("kernel", phase): s}}"""
    runs = {}
    for p in sorted(glob.glob(path("profile", folder, "*.folded.gz"))):
        header, stacks = read_folded(p)
        freq = int(header.get("freq", 1000))
        query, config = header.get("label", ",").split(",", 1)
        run = collections.defaultdict(float)
        run["wall"] = float(header.get("wall_ms", 0)) / 1000
        run["cpu"] = sum(n for _, n, _ in stacks) / freq
        for (stack, n, _), shares in zip(stacks, classify_samples(stacks)):
            for (category, sub), share in shares.items():
                seconds = n * share / freq
                run[category] += seconds
                run[(category, sub)] += seconds
                if category == "join":
                    phase, kernel = join_phase(stack)
                    run[("phase", "커널" if kernel else phase)] += seconds
                    if kernel:
                        run[("kernel", phase)] += seconds
        runs[(query, config)] = run
    return runs


def fmt(v, d=2):
    return "·" if v is None or v == "" or (isinstance(v, float) and abs(v) < 0.5 * 10**-d) else f"{v:.{d}f}"


def g1():
    top, br = stat("g1_topdown.csv"), stat("g1_branches.csv")
    if not top and not br:
        return
    print("## G1. 분기 예측 실패의 시간 비용\n")
    metric = next((k for v in top.values() for k in v if str(k).startswith("tma_bad_spec")), None)
    raw = ("uops_issued.any", "uops_retired.retire_slots", "int_misc.recovery_cycles")
    if not metric and any(all(e in v for e in raw) for v in top.values()):
        # the level-1 formula of the Skylake server cores (4 issue slots per cycle)
        metric = "bad_speculation_raw"
        for v in top.values():
            if all(e in v for e in raw):
                v[metric] = 100 * (v[raw[0]] - v[raw[1]] + 4 * v[raw[2]]) / (4 * v["cycles"])
    errors = [v["error"] for v in top.values() if "error" in v]
    if not metric:
        print("Top-down 메트릭이 측정되지 않았습니다" + (f": {errors[0]}" if errors else "") + ".\n")
    else:
        print(f"버린 cycle = `{metric}`(%) × cycles. 주파수 = cycles / task-clock. miss는 따로 잰 branch-misses(멀티플렉싱을 피하려고 "
              "Top-down과 다른 실행). 모두 1억 행, 1스레드, 측정하는 두 번째 실행만.\n")
        print("| 쿼리 (통과율) | 구성 | Bad Spec % | 버린 시간 초 | branch-miss (백만) | miss당 cycle | miss당 ns | 실행 초 |")
        print("|---|---|---|---|---|---|---|---|")
        per = {}
        for q in Q2C:
            for c in CONFIGS:
                t, b = top.get((q, c)), br.get((q, c))
                if not t or metric not in t or not b:
                    continue
                ghz = t["cycles"] / (t["task-clock"] / 1000) / 1e9
                wasted = t[metric] / 100 * t["cycles"]
                misses = b.get("branch-misses", 0)
                per[(q, c)] = (wasted, misses, ghz)
                cpm = wasted / misses if misses else None
                print(f"| {q} ({PASS[q]}) | {c} | {t[metric]:.1f} | {wasted / ghz / 1e9:.2f} | {misses / 1e6:.0f} | "
                      f"{fmt(cpm, 1)} | {fmt(cpm / ghz if cpm else None, 1)} | {t['wall']:.2f} |")
        print()
        print("통과 25% → 50%에서 늘어난 몫 (추정치는 miss 1.3억 번 × 6–8 ns = 0.8–1.0초):\n")
        print("| 구성 | 늘어난 miss (백만) | 늘어난 버린 시간 초 | 늘어난 시간 / 늘어난 miss (ns) |\n|---|---|---|---|")
        for c in CONFIGS:
            a, z = per.get(("q2_c25", c)), per.get(("q2_c50", c))
            if a and z:
                dw = (z[0] - a[0]) / z[2] / 1e9
                dm = z[1] - a[1]
                print(f"| {c} | {dm / 1e6:.0f} | {dw:.2f} | {fmt(dw * 1e9 / dm if dm else None, 1)} |")
        print()
    t, prof, brs = times("g1_sorted_time.csv"), profiles("g1sorted"), stat("g1_sorted_branches.csv")
    if t or prof:
        print("### q2_c50: trade_B vs trade_Bsorted (같은 행, leg_id 순서)\n")
        if os.path.exists(path("g1_sorted_verify.md")):
            print("검증:\n\n" + open(path("g1_sorted_verify.md")).read().strip() + "\n")
        print("| 구성 | 시간 B / Bsorted (차) | perf 원소 다루기 B / Bsorted (차) | 그 밖 범주 차 (디코드, 조립, UNNEST) | "
              "branch-miss B / Bsorted (백만) | 결과 |")
        print("|---|---|---|---|---|---|")
        for c in CONFIGS:
            a, b = t.get(("q2_c50.orig", c)), t.get(("q2_c50.sorted", c))
            pa, pb = prof.get(("q2_c50.orig", c)), prof.get(("q2_c50.sorted", c))
            ba, bb = brs.get(("q2_c50.orig", c), {}), brs.get(("q2_c50.sorted", c), {})
            if not (a and b):
                continue
            wa, wb = float(a["wall_s"]), float(b["wall_s"])
            elem = (f"{pa['원소 다루기']:.2f} / {pb['원소 다루기']:.2f} ({pa['원소 다루기'] - pb['원소 다루기']:.2f})"
                    if pa and pb else "·")
            other = (", ".join(f"{pa[k] - pb[k]:.2f}" for k in ("값 디코드", "리스트 조립", "UNNEST")) if pa and pb else "·")
            miss = (f"{ba['branch-misses'] / 1e6:.0f} / {bb['branch-misses'] / 1e6:.0f}"
                    if "branch-misses" in ba and "branch-misses" in bb else "·")
            same = "yes" if a["same_result"] == b["same_result"] == "yes" else "NO"
            print(f"| {c} | {wa:.2f} / {wb:.2f} ({wa - wb:.2f}) | {elem} | {other} | {miss} | {same} |")
        print()
        write = path("g1_sorted_write.txt")
        if os.path.exists(write):
            text = open(write).read()
            rss = re.search(r"Maximum resident set size \(kbytes\): (\d+)", text)
            el = re.search(r"Elapsed \(wall clock\) time[^:]*: ([\d:.]+)", text)
            print(f"trade_Bsorted 쓰기: {el.group(1) if el else '?'}, 최대 메모리 "
                  f"{int(rss.group(1)) / 1e6:.1f} GB.\n" if rss else "")


def g2():
    prof, st = profiles("g2"), stat("g2_stat.csv")
    if not prof:
        return
    print("## G2. q4_two: 큰 쪽(원래, c11) vs 작은 쪽(c14) build\n")
    print("perf CPU 초(새 기준). join은 해시 테이블 일을 단계로 나눈 것(categories.join_phase): 커널 = 잎이 kernel인 샘플(page fault 등).\n")
    phases = ["메모리 할당", "build (채우기)", "Finalize", "probe", "해제·소멸", "커널", "join 기타"]
    for c in ("base", "prenest"):
        a, b = prof.get(("q4_two.orig", c)), prof.get(("q4_two.small_build", c))
        if not (a and b):
            continue
        print(f"### {c}\n")
        print("| 항목 | 원래 | 작은 쪽 build | 차 (원래 − 작은 쪽) |\n|---|---|---|---|")
        print(f"| 실행 시간 (wall) | {a['wall']:.2f} | {b['wall']:.2f} | **{a['wall'] - b['wall']:.2f}** |")
        print(f"| CPU (perf) | {a['cpu']:.2f} | {b['cpu']:.2f} | {a['cpu'] - b['cpu']:.2f} |")
        for k in CATEGORIES:
            if k == "join":
                for ph in phases:
                    key = ("phase", ph)
                    if a[key] + b[key] >= 0.05:
                        print(f"| join: {ph} | {a[key]:.2f} | {b[key]:.2f} | {a[key] - b[key]:.2f} |")
                for ph in phases[:-1]:
                    key = ("kernel", ph)
                    if a[key] + b[key] >= 0.05:
                        print(f"| └ 커널 중 {ph} 단계 | {a[key]:.2f} | {b[key]:.2f} | {a[key] - b[key]:.2f} |")
            elif a[k] + b[k] >= 0.05:
                print(f"| {k} | {a[k]:.2f} | {b[k]:.2f} | {a[k] - b[k]:.2f} |")
        sa, sb = st.get(("q4_two.orig", c), {}), st.get(("q4_two.small_build", c), {})
        for item, label, scale in (("page-faults", "page fault (백만, 측정 실행)", 1e6), ("max_rss", "최대 RSS (GB, 프로세스)", 1e6)):
            if item in sa and item in sb:
                print(f"| {label} | {sa[item] / scale:.2f} | {sb[item] / scale:.2f} | {(sa[item] - sb[item]) / scale:.2f} |")
        print()


def g3():
    prof = profiles("g3")
    tp, td = times("g3_stage_parquet.csv"), times("g3_stage_db.csv")
    if not (prof or tp):
        return
    print("## G3. 둘 다 DuckDB 테이블일 때 빠른 이유\n")
    if prof:
        print("k = 4, 합계 먼저 쿼리. perf CPU 초(새 기준), (a) 사실·차원 parquet vs (c) 둘 다 DuckDB 테이블.\n")
        print("| 구성 | 범주 | (a) parquet | (c) DuckDB 테이블 | 차 (a − c) |\n|---|---|---|---|---|")
        for c in ("base", "prenest"):
            a, b = prof.get(("a_k04.preagg", c)), prof.get(("c_k04.preagg", c))
            if not (a and b):
                continue
            print(f"| {c} | 실행 시간 (wall) | {a['wall']:.2f} | {b['wall']:.2f} | **{a['wall'] - b['wall']:.2f}** |")
            for k in CATEGORIES:
                if a[k] + b[k] >= 0.05:
                    print(f"| {c} | {k} | {a[k]:.2f} | {b[k]:.2f} | {a[k] - b[k]:.2f} |")
        print()
    if tp and td:
        print("단계 쿼리 시간(초, RUNS 중 최소): parquet(trade_B) vs DuckDB 테이블(fw.trade_b).\n")
        print("| 구성 | 단계 | parquet | DuckDB 테이블 | 차 | 결과 같음 |\n|---|---|---|---|---|---|")
        for c in ("base", "prenestoff", "prenest"):
            for s in ("s1_box", "s2_unnest", "s3_cond"):
                a, b = tp.get((s, c)), td.get((s, c))
                if a and b and a["wall_s"] and b["wall_s"]:
                    same = "yes" if a["result"] == b["result"] else "NO"
                    print(f"| {c} | {s} | {float(a['wall_s']):.2f} | {float(b['wall_s']):.2f} | "
                          f"{float(a['wall_s']) - float(b['wall_s']):.2f} | {same} |")
        print()


def line_fit(xs, ys):
    """(intercept, slope, R²) of y = a + b x"""
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - a - b * x) ** 2 for x, y in zip(xs, ys))
    return a, b, (1 - ss_res / ss_tot) if ss_tot else 1.0, max(abs(y - a - b * x) for x, y in zip(xs, ys))


def g4():
    t, prof = times("g4_time.csv"), profiles("g4")
    if not t:
        return
    lists = 100_000_000
    if os.path.exists(path("g4_files.md")):
        m = re.search(r"\| syn_L1\.parquet \| ([\d,]+) \|", open(path("g4_files.md")).read())
        lists = int(m.group(1).replace(",", "")) if m else lists
        print("## G4. 단위 비용 모형 검증 (합성 BIGINT 리스트)\n\n" + open(path("g4_files.md")).read().strip() + "\n")
    else:
        print("## G4. 단위 비용 모형 검증 (합성 BIGINT 리스트)\n")
    lengths = [1, 2, 4, 8, 16, 32]
    print(f"리스트 {lists:,}개, 길이 L. 시간(또는 범주 CPU) = a + b × L 직선을 맞춤: 리스트당 = a / 리스트 수, 원소당 = b / 리스트 수.\n")
    print("| 구성 | 항목 | L = " + " / ".join(map(str, lengths)) + " (초) | 리스트당 ns | 원소당 ns | R² | 최대 잔차 초 |")
    print("|---|---|---|---|---|---|---|")
    for c in ("base", "prenestoff", "flat"):
        rows = [("실행 시간", [float(t[(f"syn_L{n:02d}", c)]["wall_s"]) for n in lengths
                              if (f"syn_L{n:02d}", c) in t and t[(f"syn_L{n:02d}", c)]["wall_s"]])]
        for k in ("값 디코드", "리스트 조립", "UNNEST", "원소 다루기", "키 생성"):
            ys = [prof[(f"syn_L{n:02d}", c)][k] for n in lengths if (f"syn_L{n:02d}", c) in prof]
            if len(ys) == len(lengths) and max(ys) >= 0.05:
                rows.append((k, ys))
        for label, ys in rows:
            if len(ys) != len(lengths):
                continue
            a, b, r2, res = line_fit(lengths, ys)
            print(f"| {c} | {label} | {' / '.join(f'{y:.2f}' for y in ys)} | {a / lists * 1e9:.1f} | {b / lists * 1e9:.2f} | "
                  f"{r2:.4f} | {res:.2f} |")
    print()
    bad = [k for k, r in t.items() if r["same_result"] != "yes"]
    print("결과: " + ("모든 구성이 base와 같음." if not bad else f"다름 {bad}") + "\n")


def main():
    print(f"# 후속 실험 G1–G4 ({os.path.basename(os.path.abspath(OUT))})\n")
    if os.path.exists(path("check.txt")):
        print("```\n" + open(path("check.txt")).read().strip()[:3000] + "\n```\n")
    g2()
    g1()
    g3()
    g4()


if __name__ == "__main__":
    main()
