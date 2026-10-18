#!/usr/bin/env python3
"""CPU lists for running 10 threads in three layouts (SERVER.md, step 9), from `lscpu -p=CPU,CORE,SOCKET`:
  one: 10 physical cores of one socket, one hardware thread each
  two: 5 physical cores of each of two sockets, one hardware thread each
  ht:  5 physical cores of one socket with both of their hardware threads
Prints "<layout> <cpu list>" per line - a layout is left out when the machine does not have it.
Usage: cpu_layouts.py [threads, default 10]
"""
import subprocess
import sys

threads = int(sys.argv[1]) if len(sys.argv) > 1 else 10
cores = {}  # (socket, core) -> hardware threads
lscpu = subprocess.run(["lscpu", "-p=CPU,CORE,SOCKET"], capture_output=True, text=True, check=True).stdout
for line in lscpu.splitlines():
    if line.startswith("#"):
        continue
    cpu, core, socket = (int(x) for x in line.split(","))
    cores.setdefault((socket, core), []).append(cpu)
sockets = sorted({socket for socket, _ in cores})
per_socket = {s: [cpus for (socket, _), cpus in sorted(cores.items()) if socket == s] for s in sockets}
layouts = {}
if len(per_socket[sockets[0]]) >= threads:
    layouts["one"] = [cpus[0] for cpus in per_socket[sockets[0]][:threads]]
if len(sockets) >= 2 and all(len(per_socket[s]) >= threads // 2 for s in sockets[:2]):
    layouts["two"] = [cpus[0] for s in sockets[:2] for cpus in per_socket[s][:threads // 2]]
with_ht = [cpus for cpus in per_socket[sockets[0]] if len(cpus) >= 2]
if len(with_ht) >= threads // 2:
    layouts["ht"] = [cpu for cpus in with_ht[:threads // 2] for cpu in cpus[:2]]
for name, cpus in layouts.items():
    print(name, ",".join(str(cpu) for cpu in cpus))
