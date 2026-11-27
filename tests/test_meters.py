#!/usr/bin/env python3
"""Checks for the PipeWire metering layer that do not need audio.

The channel mapping is the part that can be silently wrong: a mistake puts the
S/PDIF bar on the Main fader and nobody notices until a session is half mixed.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import meters


class OutputPairMapping(unittest.TestCase):
    def test_pcm_order_maps_to_the_right_faders(self):
        """PipeWire order FL FR RL RR FC LFE SL SR -> PCM pairs 1/2, 3/4, 5/6, 7/8."""
        m = meters.Meters(start=False)
        m.outputs = meters.MeterSource("x", 8,
                                       ["FL", "FR", "RL", "RR", "FC", "LFE", "SL", "SR"])
        self.assertEqual(m.output_pairs(), [[0, 1], [4, 5], [2, 3], [6, 7]])

    def test_identity_layout(self):
        m = meters.Meters(start=False)
        m.outputs = meters.MeterSource("x", 8,
                                       ["FL", "FR", "FC", "LFE", "RL", "RR", "FLC", "FRC"])
        self.assertEqual(m.output_pairs(), [[0, 1], [2, 3], [4, 5], [6, 7]])

    def test_unknown_layout_falls_back_to_pcm_order(self):
        m = meters.Meters(start=False)
        m.outputs = meters.MeterSource("x", 4, ["MONO", "MONO", "MONO", "MONO"])
        self.assertEqual(m.output_pairs()[:2], [[0, 1], [2, 3]])


class PacatMap(unittest.TestCase):
    def test_translates_pipewire_codes(self):
        self.assertEqual(meters._pacat_map(["FL", "FR"]), "front-left,front-right")
        self.assertEqual(meters._pacat_map(["LFE"]), "lfe")

    def test_unknown_code_yields_empty_map(self):
        # better no map than a wrong one: parec then keeps native order
        self.assertEqual(meters._pacat_map(["FL", "AUX3"]), "")


class DegradesGracefully(unittest.TestCase):
    def test_no_sources_gives_empty_levels_and_a_note(self):
        m = meters.Meters(start=False)
        m._discovered = True          # pretend discovery already ran and found nothing
        snap = m.snapshot()
        self.assertEqual(snap["inputs"], [])
        self.assertEqual(snap["outputs"], [])
        self.assertFalse(m.describe()["available"])

    def test_level_floor_is_96(self):
        ch = meters.Channel()
        self.assertEqual(ch.db, -96.0)


class LevelCurve(unittest.TestCase):
    """The bar scale must be monotonic and clamp at both ends."""

    @staticmethod
    def percent(db):
        return max(0, min(1, (db + 60) / 66)) * 100

    def test_scale(self):
        self.assertEqual(self.percent(-96), 0)
        self.assertGreater(self.percent(-20), self.percent(-40))
        self.assertAlmostEqual(self.percent(0), 90.9, places=1)
        self.assertEqual(self.percent(6), 100)
        self.assertEqual(self.percent(12), 100)


if __name__ == "__main__":
    unittest.main(verbosity=1)
