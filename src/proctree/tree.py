"""Pure functions over process snapshots.

Nothing in this module reads the OS process table. Callers get their
own snapshot however they like (parsing `ps -ef`, walking /proc, a
canned fixture in a test) and hand it in as a flat list of ProcessInfo
records. That split is what keeps every function here a plain
data-in, data-out transform.
"""

from __future__ import annotations

from typing import Iterable, Mapping, NamedTuple, Optional


class ProcessInfo(NamedTuple):
    pid: int
    ppid: int
    name: str


ProcessTable = Mapping[int, ProcessInfo]


def to_table(processes: Iterable[ProcessInfo]) -> ProcessTable:
    """Index a flat list of processes by pid.

    Later entries win on a duplicate pid, matching how a fresh
    snapshot would overwrite a recycled pid from an older one.
    """
    table: dict[int, ProcessInfo] = {}
    for proc in processes:
        table[proc.pid] = proc
    return table


def children_map(table: ProcessTable) -> dict[int, list[int]]:
    """Map each pid to the sorted pids of its direct children.

    A process is its own root (ppid == pid, as pid 1 often reports)
    or has a ppid missing from the table (already reaped) counts as
    having no parent inside this snapshot, not as a child of itself.
    """
    children: dict[int, list[int]] = {pid: [] for pid in table}
    for proc in table.values():
        if proc.ppid in table and proc.ppid != proc.pid:
            children[proc.ppid].append(proc.pid)
    for kids in children.values():
        kids.sort()
    return children


def roots(table: ProcessTable) -> list[int]:
    """Pids with no parent inside this snapshot, sorted."""
    return sorted(
        pid
        for pid, proc in table.items()
        if proc.ppid not in table or proc.ppid == proc.pid
    )


def ancestors(pid: int, table: ProcessTable) -> list[int]:
    """Pids from the immediate parent up to the root, nearest first.

    Stops at the first pid missing from the table or at a cycle,
    since a snapshot taken mid-fork can contain either.
    """
    chain: list[int] = []
    seen = {pid}
    proc = table.get(pid)
    while proc is not None and proc.ppid in table and proc.ppid not in seen:
        chain.append(proc.ppid)
        seen.add(proc.ppid)
        proc = table.get(proc.ppid)
    return chain


def descendants(pid: int, table: ProcessTable) -> set[int]:
    """All pids reachable below `pid`, direct or indirect."""
    kids = children_map(table)
    result: set[int] = set()
    stack = list(kids.get(pid, []))
    while stack:
        child = stack.pop()
        if child in result:
            continue
        result.add(child)
        stack.extend(kids.get(child, []))
    return result


def subtree(pid: int, table: ProcessTable) -> dict[int, ProcessInfo]:
    """The table restricted to `pid` and everything below it."""
    if pid not in table:
        return {}
    keep = descendants(pid, table) | {pid}
    return {p: table[p] for p in keep}


def render_tree(table: ProcessTable, root: Optional[int] = None) -> str:
    """Render as ASCII, one process per line, ordered by pid at each level.

    With `root` given, renders just that pid's subtree. Otherwise
    renders every root in the snapshot, in pid order.
    """
    kids = children_map(table)
    start_pids = [root] if root is not None else roots(table)
    lines: list[str] = []

    def walk(pid: int, prefix: str, connector: str, next_prefix: str) -> None:
        proc = table[pid]
        lines.append(f"{prefix}{connector}{proc.name} ({proc.pid})")
        child_pids = kids.get(pid, [])
        for i, child in enumerate(child_pids):
            last = i == len(child_pids) - 1
            walk(
                child,
                next_prefix,
                "`-- " if last else "|-- ",
                next_prefix + ("    " if last else "|   "),
            )

    for pid in start_pids:
        if pid in table:
            walk(pid, "", "", "")

    return "\n".join(lines)
