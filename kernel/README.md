# Kernel reference sources

These files are **copies of Linux kernel sources**, included only as reference
material for people extending this project. They are **GPL-2.0**, not MIT, and
they are not linked or compiled by anything here — `studio-1810c` is a userspace
program that talks to the interface through libusb.

| file | upstream path | why it is here |
|---|---|---|
| `mixer_s1810c.c` | `sound/usb/mixer_s1810c.c` | the kernel's own 1810c mixer driver: the `0xA0`/`0xA1`/`0xA2` half of the protocol, written by Nick Kossifidis |
| `mixer.c` | `sound/usb/mixer.c` | how the generic mixer core binds controls to the device |
| `quirks.c` | `sound/usb/quirks.c` | contains `s1810c_skip_setting_quirk`, which decides the altsets (and therefore channels) per sample rate |
| `quirks-table.h` | `sound/usb/quirks-table.h` | the USB quirk tables referenced by the above |

Read them against the kernel tree you are actually running — these are snapshots
and may lag upstream. The copyright headers in each file are authoritative.
