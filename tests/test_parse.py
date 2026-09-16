import unittest

from proctree import ProcessInfo
from proctree.parse import parse_ps_ef, parse_ps_eo


class ParsePsEoTests(unittest.TestCase):
    def test_parses_rows_after_header(self) -> None:
        output = (
            "  PID  PPID COMMAND\n"
            "    1     0 init\n"
            "   10     1 sshd\n"
            "   20    10 bash\n"
        )
        procs = parse_ps_eo(output)
        self.assertEqual(
            procs,
            [
                ProcessInfo(pid=1, ppid=0, name="init"),
                ProcessInfo(pid=10, ppid=1, name="sshd"),
                ProcessInfo(pid=20, ppid=10, name="bash"),
            ],
        )

    def test_ignores_blank_lines(self) -> None:
        output = "PID PPID COMMAND\n1 0 init\n\n10 1 sshd\n"
        procs = parse_ps_eo(output)
        self.assertEqual([p.pid for p in procs], [1, 10])

    def test_empty_input(self) -> None:
        self.assertEqual(parse_ps_eo(""), [])
        self.assertEqual(parse_ps_eo("PID PPID COMMAND\n"), [])


class ParsePsEfTests(unittest.TestCase):
    def test_parses_full_command_line(self) -> None:
        output = (
            "UID        PID  PPID  C STIME TTY          TIME CMD\n"
            "root         1     0  0 Jan01 ?        00:00:03 /sbin/init\n"
            "root        10     1  0 Jan01 ?        00:00:01 /usr/sbin/sshd -D\n"
            "alice       20    10  0 09:00 pts/0    00:00:00 -bash\n"
        )
        procs = parse_ps_ef(output)
        self.assertEqual(
            procs,
            [
                ProcessInfo(pid=1, ppid=0, name="init"),
                ProcessInfo(pid=10, ppid=1, name="sshd"),
                ProcessInfo(pid=20, ppid=10, name="-bash"),
            ],
        )

    def test_empty_input(self) -> None:
        self.assertEqual(parse_ps_ef(""), [])
        self.assertEqual(
            parse_ps_ef("UID PID PPID C STIME TTY TIME CMD\n"), []
        )


if __name__ == "__main__":
    unittest.main()
