import unittest

from proctree import (
    ProcessInfo,
    ancestors,
    children_map,
    descendants,
    render_tree,
    roots,
    subtree,
    to_table,
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


if __name__ == "__main__":
    unittest.main()
