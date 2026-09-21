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


def prune(pid: int, table: ProcessTable) -> ProcessTable:
    """Drop `pid` and everything below it, as if the whole subtree were killed.

    Nothing outside the subtree is touched, including processes whose
    ppid pointed into the pruned subtree from outside it (not possible
    in a real tree, but this function doesn't assume the input is one).
    """
    if pid not in table:
        return dict(table)
    drop = descendants(pid, table) | {pid}
    return {p: proc for p, proc in table.items() if p not in drop}


def reparent(pid: int, new_ppid: int, table: ProcessTable) -> ProcessTable:
    """Drop `pid` but keep its direct children, handing them to `new_ppid`.

    Models what actually happens when a single process dies: its
    children don't vanish with it, they get adopted (by init, or by
    whatever subreaper is watching) and carry on under a new parent.
    Use `prune` instead if the whole subtree should disappear.
    """
    if pid not in table:
        return dict(table)
    result: dict[int, ProcessInfo] = {}
    for p, proc in table.items():
        if p == pid:
            continue
        if proc.ppid == pid:
            result[p] = proc._replace(ppid=new_ppid)
        else:
            result[p] = proc
    return result


class Reparented(NamedTuple):
    pid: int
    old_ppid: int
    new_ppid: int


class SnapshotDiff(NamedTuple):
    started: list[ProcessInfo]
    stopped: list[ProcessInfo]
    reparented: list[Reparented]


def diff(old: ProcessTable, new: ProcessTable) -> SnapshotDiff:
    """Compare two snapshots of the same machine taken at different times.

    A pid only in `new` started, a pid only in `old` stopped. A pid in
    both with a changed ppid was reparented, whether because its
    original parent died and it got adopted, or because something
    explicitly moved it (see `reparent`). Everything else is treated
    as unchanged even if its name field differs, since a pid getting
    reused for a different program between snapshots looks the same
    as one snapshot just having stale process names.
    """
    started = sorted(
        (proc for pid, proc in new.items() if pid not in old),
        key=lambda proc: proc.pid,
    )
    stopped = sorted(
        (proc for pid, proc in old.items() if pid not in new),
        key=lambda proc: proc.pid,
    )
    reparented = sorted(
        (
            Reparented(pid, old[pid].ppid, new[pid].ppid)
            for pid in old.keys() & new.keys()
            if old[pid].ppid != new[pid].ppid
        ),
        key=lambda r: r.pid,
    )
    return SnapshotDiff(started=started, stopped=stopped, reparented=reparented)


class DuplicatePid(NamedTuple):
    pid: int
    count: int


class Cycle(NamedTuple):
    pids: tuple[int, ...]


class ValidationResult(NamedTuple):
    duplicate_pids: list[DuplicatePid]
    cycles: list[Cycle]

    def __bool__(self) -> bool:
        return not self.duplicate_pids and not self.cycles


def validate(processes: Iterable[ProcessInfo]) -> ValidationResult:
    """Check a raw snapshot for issues the rest of this module tolerates silently.

    `to_table` resolves a duplicate pid by letting the last entry win,
    and `ancestors` just stops walking when it hits a cycle. Both are
    reasonable defaults for functions that never assume a well-formed
    tree, but something building a snapshot by hand — a custom parser,
    a fuzzer, a test fixture — may want to know it got bad data instead
    of having it quietly patched over. Duplicate pids are reported
    against the raw input, before `to_table` would collapse them. A
    process reporting itself as its own parent is treated as a root
    (see `roots`), not a cycle; only a loop of two or more distinct
    pids counts.

    The result is falsy when the snapshot is clean, so `if validate(procs):`
    reads as "there's a problem".
    """
    processes = list(processes)

    counts: dict[int, int] = {}
    for proc in processes:
        counts[proc.pid] = counts.get(proc.pid, 0) + 1
    duplicate_pids = sorted(
        (DuplicatePid(pid, count) for pid, count in counts.items() if count > 1),
        key=lambda d: d.pid,
    )

    table = to_table(processes)
    in_cycle: set[int] = set()
    cycles: list[Cycle] = []
    for pid in sorted(table):
        if pid in in_cycle:
            continue
        path: list[int] = []
        visited: dict[int, int] = {}
        current = pid
        while True:
            proc = table.get(current)
            if proc is None or proc.ppid == proc.pid:
                break
            if current in in_cycle:
                # Already known to lead into a cycle found from an earlier
                # starting pid — nothing new to report.
                break
            if current in visited:
                cycle_pids = tuple(path[visited[current] :])
                cycles.append(Cycle(cycle_pids))
                in_cycle.update(cycle_pids)
                break
            visited[current] = len(path)
            path.append(current)
            current = proc.ppid

    return ValidationResult(duplicate_pids=duplicate_pids, cycles=cycles)


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
