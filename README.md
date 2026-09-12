# proctree

A small library for reasoning about process trees: given a flat list of
`(pid, ppid, name)` records, find ancestors, find descendants, pull out a
subtree, or print the whole thing as an ASCII tree.

It deliberately does not know how to read the real process table. You get a
snapshot however fits your situation — parse `ps -ef`, walk `/proc`, load a
saved fixture in a test — and hand it in as plain data. Every function here
is a pure transform: same input, same output, no I/O, no globals. That makes
the whole thing trivial to unit test and easy to reuse in places that have
nothing to do with the OS process table (build graphs, supervisor trees,
whatever else looks like a forest of parent/child records).

## Install

No PyPI package yet. Drop `src/proctree` on your path, or install from a
checkout:

```
pip install -e .
```

## Usage

```python
from proctree import ProcessInfo, to_table, ancestors, descendants, render_tree

snapshot = [
    ProcessInfo(pid=1, ppid=0, name="init"),
    ProcessInfo(pid=10, ppid=1, name="sshd"),
    ProcessInfo(pid=20, ppid=10, name="bash"),
    ProcessInfo(pid=21, ppid=20, name="vim"),
    ProcessInfo(pid=22, ppid=20, name="make"),
]

table = to_table(snapshot)

print(render_tree(table))
# init (1)
# `-- sshd (10)
#     `-- bash (20)
#         |-- vim (21)
#         `-- make (22)

print(ancestors(21, table))
# [20, 10, 1]

print(descendants(20, table))
# {21, 22}
```

Turning a real `ps -ef` snapshot into `ProcessInfo` records is a couple of
lines you write yourself, on purpose — this library has no opinion on where
your data comes from:

```python
import subprocess

def read_snapshot() -> list[ProcessInfo]:
    out = subprocess.run(
        ["ps", "-eo", "pid,ppid,comm"], capture_output=True, text=True, check=True
    ).stdout
    procs = []
    for line in out.splitlines()[1:]:
        pid, ppid, name = line.split(maxsplit=2)
        procs.append(ProcessInfo(pid=int(pid), ppid=int(ppid), name=name))
    return procs
```

## API

- `to_table(processes)` — index a flat list of `ProcessInfo` by pid.
- `children_map(table)` — pid -> sorted list of direct child pids.
- `roots(table)` — pids with no parent in the snapshot.
- `ancestors(pid, table)` — chain from the immediate parent up to the root.
- `descendants(pid, table)` — every pid reachable below `pid`.
- `subtree(pid, table)` — the table restricted to `pid` and below.
- `prune(pid, table)` — table with `pid` and its whole subtree removed, as
  if it had all been killed together.
- `reparent(pid, new_ppid, table)` — table with `pid` removed but its direct
  children handed to `new_ppid`, matching how a single killed process gets
  its orphans adopted instead of taking them down with it.
- `diff(old, new)` — compare two snapshots of the same machine, returning
  which pids started, which stopped, and which got a new ppid.
- `render_tree(table, root=None)` — ASCII rendering of the whole forest or
  one subtree.

## Running the tests

```
python -m unittest discover -s tests
```

## License

MIT, see `LICENSE`.
