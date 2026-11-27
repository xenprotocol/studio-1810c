# Studio 1810c — user manual

This is the long version of "how do I use it". If you just want to install and
open it, the [README](../README.md) is enough.

Contents

1. [What this controls, and what it does not](#1-what-this-controls-and-what-it-does-not)
2. [Installing](#2-installing)
3. [First start](#3-first-start)
4. [The window](#4-the-window)
5. [Routing: the input matrix](#5-routing-the-input-matrix)
6. [Output faders](#6-output-faders)
7. [Global switches](#7-global-switches)
8. [Presets and pushing to the device](#8-presets-and-pushing-to-the-device)
9. [Where your settings live](#9-where-your-settings-live)
10. [Troubleshooting](#10-troubleshooting)
11. [Uninstalling](#11-uninstalling)
12. [Using three inputs at once, and other workflow notes](#12-using-three-inputs-at-once-and-other-workflow-notes)
13. [FAQ](#13-faq)

---

## 1. What this controls, and what it does not

**It controls the mixer inside the interface**: which input goes to which output
pair, how loud, and panned where; the four output faders; and the five switches
that also exist on the front panel.

**It does not touch audio settings.** Sample rate, buffer size and clock source
selection belong to ALSA and to your DAW's audio device dialog. The interface
picks its rate when a client opens it, and the kernel keeps only the altsets that
match the `snd_usb_audio.device_setup` module option (see the README).

**It does not run as root**, and it does not need to. It talks to the interface
through libusb, using a udev rule that grants desktop users access.

**It cannot read the matrix back.** The protocol can write the routing but not
read it. That single fact explains most of the interface behaviour described in
[section 8](#8-presets-and-pushing-to-the-device).

---

## 2. Installing

### From the package (recommended)

```bash
sudo apt install ./studio-1810c_1.0.0_amd64.deb
```

The package installs:

- the application under `/usr/lib/studio-1810c/`
- `/usr/bin/studio-1810c` (so you can also type the name in a terminal)
- a menu entry — search for **Studio 1810c**
- the icon, a man page, and `/usr/lib/udev/rules.d/99-presonus-1810c.rules`
- a post-install step that reloads udev and re-triggers USB, so an already
  plugged-in interface becomes accessible immediately

There is no group to join and no `sudo` needed after the install.

### From source

See [BUILDING.md](BUILDING.md). Short version: `./ucapp.py` after installing
GTK 3, WebKitGTK, `python3-gi` and the udev rule.

---

## 3. First start

1. Plug the interface in (any USB 2 or 3 port; it is a USB 2 device).
2. Open **Studio 1810c** from the menu.

The header shows three chips:

| chip | meaning |
|---|---|
| **connected** | the app is talking to the interface. `device not found` if not. |
| **88.2-96 kHz** | sample-rate family the device is running, read from ALSA. `—` when nothing has opened the device yet. |
| **clock internal** | clock source reported by the device, when it can be read. |

Left of the chips the header says **not pushed to device** until the first write
of this session. That is not an error — see [section 8](#8-presets-and-pushing-to-the-device).

If the interface is plugged in *after* the app opens, it connects within a few
seconds on its own.

### If access is denied

On a source install (no package), the first launch may show a dialog: *Allow
access to the audio interface?* Press **Grant access**, type your password once,
and the app installs the udev rule and reconnects by itself. If you prefer a
terminal:

```bash
sudo install -m644 99-presonus-1810c.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger --action=add --subsystem-match=usb
```

With the `.deb` this dialog should never appear.

---

## 4. The window

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 1810c  CONTROL SURFACE   ● connected  88.2-96 kHz  clock internal        │
│ not pushed to device            [ presets ▾ ] [Save preset] [Push session]│
├──────────────┬───────────────────────────────────────────────────────────┤
│ OUTPUT       │ Main   (the pair you are editing)                         │
│  ▸ Main      │  [ Analog 1..8 ] [ S/PDIF ] [ ADAT 1..8 ] [ DAW 1..18 ]    │
│  ▸ Line 1/2  │  strip = fader, dB, pan, mute                              │
│  ▸ Line 3/4  │                                                           │
│  ▸ S/PDIF    │                                                           │
├──────────────┴──────────────┬────────────────────────────────────────────┤
│ Master: Main Line1/2 Line3/4 S/PDIF │ Global switches: 48V Line Mute Mono A/B │
├─────────────────────────────┴────────────────────────────────────────────┤
│ DEVICE TELEMETRY — eight raw values (not meters, see README)             │
│ footer: device path, firmware, address                                   │
└──────────────────────────────────────────────────────────────────────────┘
```

- **Theme button** (◐, top right) switches dark/light.
- **Ctrl+R** reloads the interface (useful if the device was replugged).
- The window remembers its size and position; state is saved automatically.

Components:

| region | what it is |
|---|---|
| **output rail** (left) | the four output pairs. Selecting one decides which matrix you are editing. |
| **strip grid** (centre) | the 36 input channels feeding the selected pair, grouped Analog / S-PDIF / ADAT / DAW. |
| **master** | output faders for all four pairs, always visible. |
| **global switches** | the five front-panel switches. |
| **meters** | the thin bars beside every fader: live level, see [Meters](#meters) below. |
| **telemetry** | eight values read from the device that have not been identified yet. Shown raw on purpose. |
| **footer** | device identity: VID:PID, bus address, firmware where readable. |

### Meters

Every fader has a thin bar beside it. They are **real levels, measured from the
audio**, not from the interface: this firmware does not report levels to the
host at all (the evidence is in `PROTOCOL.md`). The bars are computed from the
audio that PipeWire is moving, so:

- **input bars** (Analog 1–8, S/PDIF, ADAT) show what the interface is capturing;
- **output bars** (Main, Line 1/2, Line 3/4, S/PDIF) show what is being sent to
  that output pair.

The scale runs from −60 dB to +6 dB, green up to about −12 dB, amber near 0, red
at the top. The bars peak-hold for a fifth of a second and fall back at
14 dB/s, so a transient stays visible long enough to read.

If the routing ends up somewhere you did not intend, **Reset routing** in the
mixer header puts it back to the default wiring: every matrix cell muted, then
DAW 1/2 to Main, 3/4 to Line 1/2, 5/6 to Line 3/4 and 7/8 to S/PDIF at 0 dB. It
asks first, writes immediately, and updates the window to match.

Two honest limits:

- they need **PipeWire** (or PulseAudio) — if neither is running, the bars are
  simply absent and everything else works;
- they meter the **audio path**, which is what a musician wants, but it means a
  send you make in the matrix does not change an input bar: the input bar shows
  the preamp, the output bar shows what leaves the computer.

---

## 5. Routing: the input matrix

The matrix is **18 inputs × 4 output pairs**. Every input can be sent to every
pair at its own level and pan, and the mapping is per-pair: DAW 3 can be loud in
Main and quiet in Line 1/2 at the same time.

**To route an input to the selected pair**

1. Select the pair in the output rail (Main, Line 1/2, Line 3/4, S/PDIF).
2. On a strip, drag the fader to set the send level, or click the dB value and
   type a number (`-6`, `-inf`, `0`).
3. Drag the pan control for position, or leave it centred for an even send.
4. Press **M** (or the mute button) on the strip to mute that send.

**Mute all inputs** (top right of the mixer) sets every strip of the current pair
to silence — the fast way to clear a pair before rebuilding it.

A strip that is muted shows as **MUTED**, in quiet grey rather than red: on this
mixer, silence is the resting state of most sends, so red would be wallpaper.

**Levels** run from `-inf` (silence) to `+12 dB`; the fader is scaled in dB, so
the same drag distance is the same change in level wherever you are.

**Naming** follows the ports on the interface: Analog 1–8, S/PDIF, ADAT 1–8, and
DAW 1–18 (the channels your computer sends *to* the interface).

---

## 6. Output faders

The master column has one fader per output pair. These are the hardware output
volumes — they affect what leaves the box, independent of any per-input send.

- Double-click a fader label to return it to 0 dB.
- Type a value in the box for precision.
- `-inf` mutes the output; the front-panel mute switch (if engaged) is shown in
  the switches row, not here.

---

## 7. Global switches

| switch | effect |
|---|---|
| **48V** | phantom power for the two mic inputs. Engages both; there is no per-channel phantom on this model. |
| **Line** | switches the combo inputs between line and instrument level. |
| **Mute** | mutes the main output pair at the hardware, independent of the fader. |
| **Mono** | sums the main output to mono — useful for checking a mix on one speaker. |
| **A/B** | the A/B speaker compare on the monitor outputs. |

The switches row reflects what the device reports back, so if somebody presses
the physical button, the app follows within a second.

---

## 8. Presets and pushing to the device

Two separate ideas, and the difference matters:

**A preset** is a saved routing setup: all 36 strips for all four pairs, the
output faders and the switches. Saved under `~/.config/uc1810c/presets/`.

**Pushing** sends the current session to the interface.

Because the device cannot be read back, the app cannot know what the interface is
currently doing. So it does the honest thing:

- on startup the header says **not pushed to device**, even if you had the exact
  same session open yesterday;
- after any change you make, the change itself is written — and the header then
  shows the time of the last write;
- after loading a preset, nothing has been written yet: press **Push session**.

**Practical routine**

1. Build the routing once, for all four pairs.
2. **Save preset**, name it (`studio-drums`, `live-2-track`, …).
3. Next session: pick the preset, press **Push session**, play.

If you change a preset you have already pushed and want the old one back, pick
the old preset and push again — the device holds whatever was last written, and
nothing else.

---

## 9. Where your settings live

```
~/.config/uc1810c/session.json      current session
~/.config/uc1810c/presets/*.json    saved presets
```

Both are plain JSON. Backing them up is copying the folder. Deleting the folder
gives you a factory-default session (which is *not* the same as resetting the
interface — see the CLI's `reset-routing` for that).

---

## 10. Troubleshooting

**The window says "device not found".**
The app has no access to the interface, or it is not plugged in. Check:

```bash
lsusb -d 194f:010c                        # does the kernel see it?
ls -l /dev/bus/usb/*/                     # permissions on the usbfs node
./uc1810c.py doctor                        # full report
```

If `lsusb` shows it and the app does not, the udev rule is missing — see
[section 3](#if-access-is-denied).

**"Access denied" or "permission denied" in the footer.**
The udev rule is not installed, or was installed while the device was already
plugged in. Reinstall it and re-trigger:

```bash
sudo udevadm control --reload && sudo udevadm trigger --action=add --subsystem-match=usb
```

**The mixer is connected, but the sound does not change.**
Check which pair you are editing (top of the mixer): the matrix is per-pair, and
a send you set on Main does nothing for Line 1/2. Then confirm the output fader
for that pair is up, and that the front-panel **Mute** is not engaged.

**The app opens but the page is blank.**
Press **Ctrl+R**. If it stays blank, the window's browser engine failed to start;
run the app from a terminal (`studio-1810c`) and read the error. On a source
install this usually means WebKitGTK is missing.

**Everything is silent after a reboot.**
The interface powers up with its own defaults. Open the app, pick your preset,
**Push session**.

**Audio glitches when the app is open.**
It should not — the app only sends EP0 control transfers. If you see this, report
it with the output of `./uc1810c.py doctor` and your kernel version.

**The interface is at the wrong sample rate.**
That is ALSA, not this app: set `snd_usb_audio.device_setup`, or let your DAW
choose the rate by opening the device.

---

## 11. Uninstalling

```bash
sudo apt remove studio-1810c
```

Your presets and session stay in `~/.config/uc1810c/`; delete that folder to be
rid of them. The udev rule is removed with the package (the uninstall leaves the
interface at its last written routing — nothing was ever changed permanently).

---

## 12. Using three inputs at once, and other workflow notes

- **Recording a band**: Analog 1–8 are the inputs; route each to its own DAW
  channel in the interface, and record 8 tracks. Keep Main for monitoring.
- **Zero-latency monitoring**: route the analog inputs to Main directly (that is
  what `reset-routing` gives you) and mute the DAW returns in the monitor path.
- **Two different monitor mixes**: Main for the control room, Line 1/2 for the
  headphone amp; the matrix can feed them different levels per input.
- **Sending to a stream**: S/PDIF pair can carry a separate mix with its own
  fader, so the stream hears something different from the room.
- **Pressing the front-panel buttons** is fine at any time; the app follows.

---

## 13. FAQ

**Will this work with the 1824 or 1824c?**
Probably — same vendor, same protocol family, adjacent product IDs. It is
untested; the model table is in `uc1810c.py` if you want to try (open an issue).

**Does it work while my DAW is playing?**
Yes. That is the point of the design: control transfers over EP0 do not disturb
the streaming interfaces, so audio never stops.

**Does it change my interface's firmware?**
No. It writes mixer and routing state only. Nothing in this project touches
flash, and there is no code path that could.

**Why is the telemetry panel showing numbers I cannot use?**
Those eight values are not meters and are not documented. They are shown raw
because inventing a scale would be inventing data.

**Can I control it from a script?**
Yes — `uc1810c.py` is the same protocol layer, with `--dry-run` to see the
transfers without sending them.

**Why does it say "not pushed to device" right after I opened it?**
Because the device cannot be read back, so the app genuinely does not know. One
press of **Push session** resolves it.

**Is a Windows/macOS Universal Control session compatible?**
Only in the sense that both programs write the same matrix. This app does not
read or write Universal Control's preset files.

---

*Manual for version 1.0.0. If something here is wrong, it is a bug — please open
an issue.*
