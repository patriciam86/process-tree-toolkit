"""Opt-in parsers for common `ps` output formats.

Kept out of the top-level package on purpose: the rest of this library
never touches the OS or a subprocess, and importing this module is how
a caller opts into that instead of it happening implicitly. Two shapes
are covered because they disagree on what the last column looks like:
`ps -eo pid,ppid,comm` gives a bare executable name with no spaces,
`ps -ef` gives a full command line that has to be split apart to find
just the name.
"""

from __future__ import annotations

from .tree import ProcessInfo


def parse_ps_eo(output: str) -> list[ProcessInfo]:
    """Parse `ps -eo pid,ppid,comm` output (or any pid/ppid/name order).

    Expects a header line followed by one process per line, with pid,
    ppid, and a name column that has no embedded spaces (true for
    `comm`, not for a full command line — use `parse_ps_ef` for that).
    """
    lines = output.strip().splitlines()
    if not lines:
        return []
    procs = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        pid_s, ppid_s, name = line.split(maxsplit=2)
        procs.append(ProcessInfo(pid=int(pid_s), ppid=int(ppid_s), name=name))
    return procs


def parse_ps_ef(output: str) -> list[ProcessInfo]:
    """Parse `ps -ef` (System V style) output.

    Columns are UID PID PPID C STIME TTY TIME CMD, where CMD is the
    full command line and may contain its own spaces, so it's taken
    as everything past the seventh field rather than split further.
    The stored name is the command's basename, to match the bare
    executable name `parse_ps_eo` produces.
    """
    lines = output.strip().splitlines()
    if not lines:
        return []
    procs = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        fields = line.split(maxsplit=7)
        pid = int(fields[1])
        ppid = int(fields[2])
        cmd = fields[7] if len(fields) > 7 else ""
        argv0 = cmd.split(maxsplit=1)[0] if cmd else ""
        name = argv0.rsplit("/", 1)[-1]
        procs.append(ProcessInfo(pid=pid, ppid=ppid, name=name))
    return procs
