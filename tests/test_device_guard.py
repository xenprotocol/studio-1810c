#!/usr/bin/env python3
"""The app must refuse the other Studio models, and say which one it found.

The 1824 and 1824c have a different matrix size, so writing the 1810c layout to
one would land levels in the wrong cells. Refusing is correct; refusing silently
is what makes people think the app is broken.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ucd = __import__("ucd")                    # noqa: E402
import uc1810c as uc                       # noqa: E402
uc._ensure_pyusb()
import usb.core                            # noqa: E402


class DeviceGuard(unittest.TestCase):
    def setUp(self):
        self.orig = usb.core.find

    def tearDown(self):
        usb.core.find = self.orig

    def plug(self, pid):
        usb.core.find = lambda **kw: object() if kw.get("idProduct") == pid else None

    def test_names_the_1824(self):
        self.plug(0x0107)
        note = ucd.other_interface_note()
        self.assertIn("Studio 1824", note)
        self.assertIn("0107", note)
        self.assertIn("nothing was written", note)

    def test_names_the_1824c(self):
        self.plug(0x010D)
        self.assertIn("Studio 1824c", ucd.other_interface_note())

    def test_silent_when_nothing_is_plugged(self):
        usb.core.find = lambda **kw: None
        self.assertIsNone(ucd.other_interface_note())

    def test_a_broken_usb_stack_does_not_raise(self):
        def boom(**kw):
            raise OSError("no libusb")
        usb.core.find = boom
        self.assertIsNone(ucd.other_interface_note())


class WrongDeviceIsReported(unittest.TestCase):
    """Surface._start_device must surface the model note rather than a generic error."""

    def test_error_names_the_model(self):
        orig_find = usb.core.find
        orig_dev = uc.Dev
        try:
            usb.core.find = lambda **kw: object() if kw.get("idProduct") == 0x0107 else None
            uc.Dev = lambda *a, **k: (_ for _ in ()).throw(SystemExit("no device"))
            surface = ucd.Surface()
            self.assertIn("Studio 1824", surface.error or "")
        finally:
            usb.core.find = orig_find
            uc.Dev = orig_dev


if __name__ == "__main__":
    unittest.main(verbosity=1)
