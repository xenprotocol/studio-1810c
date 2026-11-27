#!/usr/bin/env python3
"""Reset routing: what it writes, and that the window mirrors it.

The real function writes to the interface, so the device is stubbed. What is
worth testing is the state the window ends up showing — if that disagrees with
the device, the user reads a lie.
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ucd          # noqa: E402


class FakeDev:
    def __init__(self):
        self.calls = 0

    def reset_routing(self):
        self.calls += 1


def bare_surface():
    s = object.__new__(ucd.Surface)
    s.dev = FakeDev()
    s.error = None
    s.lock = threading.RLock()
    s.state = {"strips": {}, "outputs": {}, "switches": {}, "applied_at": None}
    s.save = lambda: None
    return s


class ResetRouting(unittest.TestCase):
    def setUp(self):
        self.s = bare_surface()
        self.applied = self.s.reset_routing()

    def test_device_is_written_once(self):
        self.assertEqual(self.s.dev.calls, 1)

    def test_outputs_go_to_unity_and_unmute(self):
        self.assertEqual(len(self.s.state["outputs"]), len(ucd.PAIR_NAMES))
        for out in self.s.state["outputs"].values():
            self.assertEqual(out["db"], 0.0)
            self.assertFalse(out["mute"])

    def test_every_cell_is_muted_except_direct_daw_pairs(self):
        strips = self.s.state["strips"]
        self.assertEqual(len(strips), 36 * len(ucd.PAIR_NAMES))
        open_cells = {k for k, v in strips.items() if not v["mute"]}
        expected = {"%d:%d" % (pair, 18 + 2 * pair + side)
                    for pair in range(4) for side in (0, 1)}
        self.assertEqual(open_cells, expected)
        for key in expected:
            self.assertEqual(strips[key]["level_db"], 0.0)

    def test_reports_when_it_was_applied(self):
        self.assertTrue(self.applied)

    def test_raises_without_a_device(self):
        s = bare_surface()
        s.dev = None
        with self.assertRaises(RuntimeError):
            s.reset_routing()


if __name__ == "__main__":
    unittest.main(verbosity=1)
