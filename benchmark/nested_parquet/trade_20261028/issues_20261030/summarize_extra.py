#!/usr/bin/env python3
"""The tables of the follow-ups (2026-11), as markdown on stdout, from what is present in the folders given:

  A  bn_verify.md, bn_time.csv, profile/bn/: trade_B against trade_Bn1/Bn2 - time and perf categories (new basis),
     the list assembly and its copy functions (SetInvalid, string / validity / buffer copies) side by side
  B  profile/repro1/, profile/repro2/ (and REPRO_REF, the first run: a profile/params folder of issue 1): the share
     of every category per run and its spread (max - min, percentage points); more than 5 points is marked
  D  fanout.csv: q7_plots' shape per storage, k and configuration - the original query, the aggregation first, and
     whether partial_aggregate_pushdown put an aggregate below the join (plan_flag of EXPORT_STATE)

Usage: [REPRO_REF=<issue1 folder>/profile/params] summarize_extra.py <folder> ...
"""
import collections
import csv
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from categories import CATEGORIES, classify_samples, read_folded  # noqa: E402

SHORT = {"값 디코드": "디코드", "리스트 조립": "조립", "UNNEST": "UNNEST", "원소 다루기": "원소", "키 생성": "키",
         "join": "join", "집계": "집계", "기타": "기타"}
COPIES = ["TemplatedValidityMask<unsigned long>::SetInvalid", "VectorStringBuffer::CopyInternal",
          "ValidityMask::CopySel", "VectorBuffer::Copy"]


def runs_of(folder):
    """{(query, config): {"wall", "cpu", category: s, ("leaf", category, function): s}} from the folded stacks."""
    runs = {}
    for path in sorted(glob.glob(os.path.join(folder, "*.folded.gz"))):
        header, stacks = read_folded(path)
        freq = int(header.get("freq", 1000))
        query, config = header.get("label", ",").split(",", 1)
        run = collections.defaultdict(float)
        run["wall"] = float(header.get("wall_ms", 0)) / 1000
        run["cpu"] = sum(n for _, n, _ in stacks) / freq
        for (stack, n, _), shares in zip(stacks, classify_samples(stacks)):
            for (category, _), share in shares.items():
                run[category] += n * share / freq
                run[("leaf", category, stack[0][0].replace("duckdb::", ""))] += n * share / freq
        runs[(query, config)] = run
    return runs


def fmt(v, digits=2):
    return "·" if v is None or abs(v) < 0.5 * 10**-digits else f"{v:.{digits}f}"


def section_a(folder):
    path = os.path.join(folder, "bn_time.csv")
    if not os.path.exists(path):
        return
    times = {(r["name"], r["config"]): r for r in csv.DictReader(open(path))}
    perf = runs_of(os.path.join(folder, "profile", "bn"))
    print("## A. 가지치기된 필드의 빈칸 복사 비용 (실측)\n")
    verify = os.path.join(folder, "bn_verify.md")
    if os.path.exists(verify):
        print("파일 검증(trade_B와 비교):\n\n" + open(verify).read().strip() + "\n")
    print("시간은 1스레드, RUNS 중 최소. perf는 새 기준(call stack). B − Bn이 양수면 Bn(빈칸 없음)이 빠름.\n")
    print("| 쿼리 | 구성 | 시간 B / Bn / B − Bn | 결과 | perf CPU B − Bn | 조립 B / Bn / 차 | 복사 함수 (조립 안) B − Bn | 디코드 B − Bn |")
    print("|---|---|---|---|---|---|---|---|")
    for q, bn in (("q2_s50", "bn1"), ("q2_c50", "bn2")):
        for config in ("base", "prenestoff", "prenest", "flat"):
            tb, tn = times.get((f"{q}.orig", config)), times.get((f"{q}.{bn}", config))
            if not (tb and tn):
                continue
            wb, wn = float(tb["wall_s"] or "nan"), float(tn["wall_s"] or "nan")
            same = "yes" if tb["same_result"] == tn["same_result"] == "yes" else "NO"
            pb, pn = perf.get((f"{q}.orig", config)), perf.get((f"{q}.{bn}", config))
            if pb and pn:
                copies = sum(pb[("leaf", "리스트 조립", f)] - pn[("leaf", "리스트 조립", f)] for f in COPIES)
                cells = (f"{fmt(pb['cpu'] - pn['cpu'])} | {fmt(pb['리스트 조립'])} / {fmt(pn['리스트 조립'])} / "
                         f"{fmt(pb['리스트 조립'] - pn['리스트 조립'])} | {fmt(copies)} | {fmt(pb['값 디코드'] - pn['값 디코드'])}")
            else:
                cells = "· | · | · | ·"
            print(f"| {q} ({bn}) | {config} | {wb:.2f} / {wn:.2f} / {wb - wn:.2f} | {same} | {cells} |")
    print()
    print("복사 함수 = 리스트 조립 범주 안에서 잎이 " + ", ".join(f"`{f}`" for f in COPIES) + "인 샘플.\n")


def section_b(folder):
    passes = [os.path.join(folder, "profile", p) for p in ("repro1", "repro2")]
    if not all(os.path.isdir(p) for p in passes):
        return
    ref = os.environ.get("REPRO_REF")
    sources = ([ref] if ref and os.path.isdir(ref) else []) + passes
    runs = [runs_of(p) for p in sources]
    keys = sorted(set.intersection(*(set(r) for r in runs)))
    print("## B. perf 재현성\n")
    print(f"같은 조건으로 {len(sources)}번 돌린 perf의 범주 비율(CPU 대비 %). 실행: " + ", ".join(
        os.path.relpath(s, folder) for s in sources) + ". 차 = 최대 − 최소(퍼센트포인트), **굵게** = 5%p 초과.\n")
    print("| 쿼리 | 구성 | CPU 초 (실행별) | " + " | ".join(SHORT[c] for c in CATEGORIES) + " | 가장 큰 차 |")
    print("|---|---|---|" + "---|" * len(CATEGORIES) + "---|")
    worst = []
    for key in keys:
        cells, spread_max = [], 0.0
        for category in CATEGORIES:
            shares = [100 * r[key][category] / r[key]["cpu"] for r in runs]
            spread = max(shares) - min(shares)
            spread_max = max(spread_max, spread)
            text = f"{min(shares):.0f}–{max(shares):.0f} ({spread:.1f})" if max(shares) >= 0.5 else "·"
            cells.append(f"**{text}**" if spread > 5 else text)
            worst.append((spread, key, category))
        cpus = " / ".join(f"{r[key]['cpu']:.1f}" for r in runs)
        print(f"| {key[0]} | {key[1]} | {cpus} | " + " | ".join(cells) + f" | {spread_max:.1f}%p |")
    print()
    over = [w for w in worst if w[0] > 5]
    print("5%p를 넘는 범주: " + (", ".join(f"{k[0]} {k[1]} {c} {s:.1f}%p" for s, k, c in sorted(over, reverse=True))
                                if over else "없음") + ".\n")


def section_d(folder):
    path = os.path.join(folder, "fanout.csv")
    if not os.path.exists(path):
        return
    rows = list(csv.DictReader(open(path)))
    table = collections.defaultdict(dict)
    for r in rows:
        storage, rest = r["name"].split("_", 1)
        k, form = rest.split(".")
        table[(storage, int(k[1:]), r["config"])][form] = r
    print("## D. 줄이 불어나는 정도(k)에 따른 '합계 먼저'\n")
    print("k = 시나리오마다 붙는 날짜 수(원소 하나가 join 뒤 k줄이 됨). 시간은 1스레드, RUNS 중 최소. 자동 = 원래 쿼리의 실행 계획에서 "
          "partial_aggregate_pushdown이 집계를 join 아래로 내렸는지(EXPORT_STATE).\n")
    storages = {"a": "(a) 사실·차원 parquet", "b": "(b) 사실 parquet, 차원 내부 테이블", "c": "(c) 둘 다 내부 테이블"}
    bad = [(r["name"], r["config"]) for r in rows if r["same_result"] != "yes"]
    print("결과: " + ("모든 변형이 원래와 같음." if not bad else "다름: " + ", ".join(f"{n} {c}" for n, c in bad)) + "\n")
    for storage, title in storages.items():
        configs = [c for c in ("base", "prenest", "flat", "pureflat") if any(key[0] == storage and key[2] == c for key in table)]
        if not configs:
            continue
        print(f"### {title}\n")
        print("| k | " + " | ".join(f"{c}: 원래 / 합계 먼저 (배수) / 자동" for c in configs) + " |")
        print("|---|" + "---|" * len(configs))
        for k in sorted({key[1] for key in table if key[0] == storage}):
            cells = []
            for c in configs:
                e = table.get((storage, k, c), {})
                o, p = e.get("orig"), e.get("preagg")
                if not (o and o["wall_s"] and p and p["wall_s"]):
                    cells.append("·")
                    continue
                ratio = float(p["wall_s"]) / float(o["wall_s"])
                cells.append(f"{float(o['wall_s']):.2f} / {float(p['wall_s']):.2f} ({ratio:.2f}) / {o['plan_flag'] or '·'}")
            print(f"| {k} | " + " | ".join(cells) + " |")
        print()


def main():
    print("# 후속 실험 (A 빈칸 복사, B perf 재현성, D 합계 먼저 곡선)\n")
    for folder in sys.argv[1:]:
        section_a(folder)
        section_b(folder)
        section_d(folder)


if __name__ == "__main__":
    main()
