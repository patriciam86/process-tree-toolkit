import unittest

from proctree import (
    Cycle,
    DuplicatePid,
    ProcessInfo,
    Reparented,
    ancestors,
    children_map,
    descendants,
    diff,
    prune,
    render_tree,
    reparent,
    roots,
    subtree,
    to_table,
    validate,
)

SAMPLE = [
    ProcessInfo(pid=1, ppid=0, name="init"),
    ProcessInfo(pid=10, ppid=1, name="sshd"),
    ProcessInfo(pid=20, ppid=10, name="bash"),
    ProcessInfo(pid=21, ppid=20, name="vim"),
    ProcessInfo(pid=22, ppid=20, name="make"),
    ProcessInfo(pid=30, ppid=1, name="cron"),
]


class TreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = to_table(SAMPLE)

    def test_to_table_last_pid_wins(self) -> None:
        dup = SAMPLE + [ProcessInfo(pid=1, ppid=0, name="init-v2")]
        table = to_table(dup)
        self.assertEqual(table[1].name, "init-v2")

    def test_children_map(self) -> None:
        kids = children_map(self.table)
        self.assertEqual(kids[1], [10, 30])
        self.assertEqual(kids[20], [21, 22])
        self.assertEqual(kids[21], [])

    def test_roots_with_missing_parent(self) -> None:
        self.assertEqual(roots(self.table), [1])

        orphan = ProcessInfo(pid=99, ppid=98, name="orphan")
        table = to_table(SAMPLE + [orphan])
        self.assertEqual(roots(table), [1, 99])

    def test_ancestors(self) -> None:
        self.assertEqual(ancestors(21, self.table), [20, 10, 1])
        self.assertEqual(ancestors(1, self.table), [])

    def test_ancestors_stops_on_cycle(self) -> None:
        cyclic = to_table(
            [
                ProcessInfo(pid=1, ppid=2, name="a"),
                ProcessInfo(pid=2, ppid=1, name="b"),
            ]
        )
        self.assertEqual(ancestors(1, cyclic), [2])

    def test_descendants(self) -> None:
        self.assertEqual(descendants(20, self.table), {21, 22})
        self.assertEqual(descendants(1, self.table), {10, 20, 21, 22, 30})
        self.assertEqual(descendants(21, self.table), set())

    def test_subtree(self) -> None:
        sub = subtree(20, self.table)
        self.assertEqual(set(sub), {20, 21, 22})
        self.assertEqual(subtree(999, self.table), {})

    def test_prune_drops_subtree(self) -> None:
        pruned = prune(20, self.table)
        self.assertEqual(set(pruned), {1, 10, 30})

    def test_prune_missing_pid_is_noop(self) -> None:
        pruned = prune(999, self.table)
        self.assertEqual(set(pruned), set(self.table))

    def test_prune_leaf(self) -> None:
        pruned = prune(21, self.table)
        self.assertEqual(set(pruned), {1, 10, 20, 22, 30})

    def test_reparent_adopts_children(self) -> None:
        adopted = reparent(20, 1, self.table)
        self.assertNotIn(20, adopted)
        self.assertEqual(adopted[21].ppid, 1)
        self.assertEqual(adopted[22].ppid, 1)
        self.assertEqual(children_map(adopted)[1], sorted([10, 21, 22, 30]))

    def test_reparent_leaves_unrelated_processes_alone(self) -> None:
        adopted = reparent(20, 1, self.table)
        self.assertEqual(adopted[10], self.table[10])
        self.assertEqual(adopted[30], self.table[30])

    def test_reparent_missing_pid_is_noop(self) -> None:
        adopted = reparent(999, 1, self.table)
        self.assertEqual(adopted, dict(self.table))

    def test_render_tree_root(self) -> None:
        text = render_tree(self.table, root=20)
        self.assertEqual(
            text,
            "bash (20)\n"
            "|-- vim (21)\n"
            "`-- make (22)",
        )

    def test_render_tree_full(self) -> None:
        text = render_tree(self.table)
        lines = text.splitlines()
        self.assertEqual(lines[0], "init (1)")
        self.assertTrue(lines[-1].endswith("`-- cron (30)"))
        self.assertTrue(any(line.endswith("`-- make (22)") for line in lines))
        self.assertEqual(len(lines), len(self.table))


class ValidateTests(unittest.TestCase):
    def test_clean_snapshot_is_valid(self) -> None:
        result = validate(SAMPLE)
        self.assertTrue(result)
        self.assertEqual(result.duplicate_pids, [])
        self.assertEqual(result.cycles, [])

    def test_detects_duplicate_pid(self) -> None:
        dup = SAMPLE + [ProcessInfo(pid=10, ppid=1, name="sshd-v2")]
        result = validate(dup)
        self.assertFalse(result)
        self.assertEqual(result.duplicate_pids, [DuplicatePid(pid=10, count=2)])
        self.assertEqual(result.cycles, [])

    def test_self_loop_is_a_root_not_a_cycle(self) -> None:
        processes = [
            ProcessInfo(pid=1, ppid=1, name="init"),
            ProcessInfo(pid=10, ppid=1, name="sshd"),
        ]
        result = validate(processes)
        self.assertTrue(result)

    def test_detects_cycle(self) -> None:
        processes = [
            ProcessInfo(pid=1, ppid=2, name="a"),
            ProcessInfo(pid=2, ppid=1, name="b"),
        ]
        result = validate(processes)
        self.assertFalse(result)
        self.assertEqual(result.duplicate_pids, [])
        self.assertEqual(result.cycles, [Cycle(pids=(1, 2))])

    def test_cycle_reported_once_not_per_member(self) -> None:
        processes = [
            ProcessInfo(pid=1, ppid=2, name="a"),
            ProcessInfo(pid=2, ppid=1, name="b"),
        ]
        result = validate(processes)
        self.assertEqual(len(result.cycles), 1)

    def test_process_pointing_into_a_cycle_is_not_itself_in_it(self) -> None:
        processes = [
            ProcessInfo(pid=1, ppid=2, name="a"),
            ProcessInfo(pid=2, ppid=1, name="b"),
            ProcessInfo(pid=5, ppid=1, name="orphaned-into-cycle"),
        ]
        result = validate(processes)
        self.assertEqual(result.cycles, [Cycle(pids=(1, 2))])


class DiffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = to_table(SAMPLE)

    def test_diff_no_change(self) -> None:
        result = diff(self.table, self.table)
        self.assertEqual(result.started, [])
        self.assertEqual(result.stopped, [])
        self.assertEqual(result.reparented, [])

    def test_diff_started(self) -> None:
        new = to_table(SAMPLE + [ProcessInfo(pid=40, ppid=1, name="httpd")])
        result = diff(self.table, new)
        self.assertEqual(result.started, [ProcessInfo(pid=40, ppid=1, name="httpd")])
        self.assertEqual(result.stopped, [])
        self.assertEqual(result.reparented, [])

    def test_diff_stopped(self) -> None:
        new = to_table(p for p in SAMPLE if p.pid != 22)
        result = diff(self.table, new)
        self.assertEqual(result.started, [])
        self.assertEqual(result.stopped, [ProcessInfo(pid=22, ppid=20, name="make")])
        self.assertEqual(result.reparented, [])

    def test_diff_reparented(self) -> None:
        new = to_table(reparent(20, 1, self.table).values())
        result = diff(self.table, new)
        self.assertEqual(result.started, [])
        self.assertEqual(result.stopped, [ProcessInfo(pid=20, ppid=10, name="bash")])
        self.assertEqual(
            result.reparented,
            [Reparented(pid=21, old_ppid=20, new_ppid=1), Reparented(pid=22, old_ppid=20, new_ppid=1)],
        )

    def test_diff_ignores_name_only_change(self) -> None:
        new = to_table(
            p._replace(name="bash-v2") if p.pid == 20 else p for p in SAMPLE
        )
        result = diff(self.table, new)
        self.assertEqual(result.started, [])
        self.assertEqual(result.stopped, [])
        self.assertEqual(result.reparented, [])


if __name__ == "__main__":
    unittest.main()
