import json, subprocess, sys
binary, data, sql = sys.argv[1], sys.argv[2], open(sys.argv[3]).read() if sys.argv[3].endswith('.sql') else sys.argv[3]
import os
q = f"SET threads = 1; {os.environ.get('SETUP', '')} EXPLAIN (ANALYZE, FORMAT json) {sql.strip().rstrip(';')}"
out = subprocess.run([binary, '-no-agent', '-list', '-noheader', '-c', q], capture_output=True, text=True, cwd=data).stdout
d = json.loads(out[out.index('{'):out.rindex('}') + 1])
def walk(n, depth, role=''):
    if n['type'] not in ('RESULT_COLLECTOR', 'EXPLAIN_ANALYZE'):
        x = n.get('extra_info', {})
        est = x.get('Estimated Cardinality', '')
        info = x.get('Node') or x.get('Function') or x.get('Conditions') or x.get('Aggregates') or x.get('Projections') or ''
        if isinstance(info, list): info = ', '.join(info)
        file = x.get('Filename(s)') or x.get('File') or ''
        print(f"{'  ' * depth}{role}{n['type']:<20} {n['timing']:8.3f}s  rows {n.get('operator_cardinality', n.get('intermediate_rows', '')):>10}  est {est:>10}  {str(info)[:60]} {str(file)[:40]}")
        depth += 1
    kids = n.get('children', [])
    for i, c in enumerate(kids):
        walk(c, depth, ('probe: ' if i == 0 else 'build: ') if n['type'] == 'HASH_JOIN' else '')
for n in d['operator']: walk(n, 0)
print('total', round(d['query']['total_time'], 3))
