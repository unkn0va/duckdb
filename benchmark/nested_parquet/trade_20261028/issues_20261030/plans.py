"""EXPLAIN (ANALYZE, FORMAT json) of a query as a list of operators, and the plan as indented text (issue 2)."""
import json
import subprocess


def explain_analyze(binary, data_dir, setup, query, threads, timeout=7200):
    """The profile JSON of the query, or raises RuntimeError with DuckDB's message."""
    script = f"SET threads = {threads};\n{setup}\nEXPLAIN (ANALYZE, FORMAT json) {query.strip().rstrip(';')};\n"
    run = subprocess.run(
        [binary, "-no-agent", "-list", "-noheader"],
        input=script,
        text=True,
        capture_output=True,
        cwd=data_dir,
        timeout=timeout,
    )
    if run.returncode or "{" not in run.stdout:
        raise RuntimeError((run.stderr.strip() or run.stdout.strip() or f"exit {run.returncode}").splitlines()[0][:300])
    out = run.stdout
    return json.loads(out[out.index("{") : out.rindex("}") + 1])


def estimate(node):
    value = node.get("extra_info", {}).get("Estimated Cardinality")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def operators(profile):
    """[dict(id, parent, depth, role, type, est, actual, timing, extra)] in pre-order. role: the side of the parent
    join (probe = first child, build = second) or ''."""
    result = []

    def walk(node, parent, depth, role):
        if node["type"] in ("RESULT_COLLECTOR", "EXPLAIN_ANALYZE"):
            for child in node.get("children", []):
                walk(child, parent, depth, role)
            return
        entry = {
            "id": len(result),
            "parent": parent,
            "depth": depth,
            "role": role,
            "type": node["type"],
            "est": estimate(node),
            "actual": node.get("intermediate_rows", node.get("operator_cardinality")),
            "timing": node.get("timing", 0.0),
            "extra": node.get("extra_info", {}),
        }
        result.append(entry)
        children = node.get("children", [])
        is_join = "JOIN" in node["type"] or node["type"] in ("CROSS_PRODUCT", "POSITIONAL_SCAN")
        for i, child in enumerate(children):
            walk(child, entry["id"], depth + 1, ("probe" if i == 0 else "build") if is_join else "")

    for node in profile["operator"]:
        walk(node, None, 0, "")
    return result


def describe(extra):
    """The few words of an operator's extra info that identify it."""
    parts = []
    for key in ("Filename(s)", "File", "Node", "Conditions", "Groups", "Aggregates", "Filters"):
        value = extra.get(key)
        if value:
            value = ", ".join(value) if isinstance(value, list) else str(value)
            parts.append(f"{key.lower().rstrip('(s)')}: {value}")
    return "; ".join(parts)


def tree_text(profile):
    lines = []
    for op in operators(profile):
        role = f"{op['role']}: " if op["role"] else ""
        est = "" if op["est"] is None else op["est"]
        lines.append(
            f"{'  ' * op['depth']}{role}{op['type']:<20} {op['timing']:8.3f}s  rows {op['actual']:>12}  est {est:>12}"
            f"  {describe(op['extra'])[:150]}"
        )
    lines.append(f"total {profile['query']['total_time']:.3f} s")
    return "\n".join(lines)
