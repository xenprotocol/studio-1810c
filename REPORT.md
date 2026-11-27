# Reverse engineering report - Fender Universal Control 5.1.1 (macOS)

Target: `Fender_Universal_Control_v5_1_1_113315.dmg` (the macOS installer, extracted locally)
Goal: get the Studio 1810c's full control surface working on Linux, where
ALSA only exposes four switches and hard-wires the mixer to a bypass.

## Unpacking chain

```
dmg  (UDIF, zlib blocks)
 -> 7z x          -> "Fender Universal Control/" (HFS+ image contents)
 -> xar (pkg)     -> Distribution, [TOC].xml, 5 component packages
 -> Payload       -> gzip+cpio (Apple "Payload~")  -> cpio -idm
```

Result, 216 MB of payload in five packages:

```
Control Panel.pkg   /Applications/Universal Control.app  (+ two DriverKit dexts)
Daemon.pkg          /Library/Application Support/PreSonus/universalcontrol/
                      ucdaemon.bundle  (hwaccess/*.dylib, one per device family)
TB Driver.pkg       HAL driver + MIDI driver for Thunderbolt Quantums
TB Driver (kext)    legacy kext variant
DefaultPresets.pkg  StudioLive scene/preset data (not relevant to USB)
```

`Universal Control.app` is only the UI; the process that talks to the device is
`ucdaemon` plus the per-family `hwaccess/*.dylib`. For the 1810c that is
`hwaccess/dspusbdevice.dylib` ("DSP USB Hardware Access"); `studiousbdevice.dylib`
is the older Studio-series sibling that shares the same parameter layer.

All binaries are Universal x86_64+arm64, fully stripped (no `__LINKEDIT` symbol
table), signed "Developer ID Application: Fender Digital, LLC (64H3QYW26T)".
The USB stack is Thesycon's TSUSBAudio SDK (`namespace thesycon`), visible in
the DriverKit binary's object paths:

```
/Volumes/External/jenkins/mac/quantum/submodules/thesycon/driversources/
  tusbaudio_macos/source/... tusbaudiodriver.build
```

## Method

1. **Static structure**: split fat slices in Python, `file`/`strings` census of
   all 189 Mach-O files, then Ghidra 11.2 headless (`-import`, full analysis,
   two post-scripts) on the two `hwaccess` dylibs.
2. **Function -> string map**: `DumpFuncStrings.py` walks every function body and
   records the strings and callees it references, producing a greppable CSV of
   2,127 + 2,676 rows. That is what pointed at
   `OpenBulkCmdDevice`, `SendCommand`, `GetDspParameters`, `SwitchAudioMode`.
3. **Constant scan**: `FindConsts.py` lists every instruction whose immediate is
   one of the request codes. That found the two functions that use `0xA1`/`0xA2`
   (`FUN_0007df80`) and the `0xD0`-`0xD4` cluster.
4. **Targeted decompilation**: `DecompileList.py` decompiles a chosen address
   list into a text file, iterated until the wrappers resolved to raw request
   fields.
5. **Ground truth**: the Linux kernel already documents `0xA0`/`0xA1`/`0xA2`
   (`sound/usb/mixer_s1810c.c`, itself derived from usbmon captures of the
   Windows driver + Universal Control). Every structure in the tool is checked
   byte-for-byte against those constants.

## Evidence ledger

| claim | evidence | strength |
|---|---|---|
| 1810c = 0x194f:0x010c, model 0x1_194f_010c, family 4 "Demeter" | kernel `quirks.c:1704`; `dspusbdevice` model table `FUN_0006f760` line `FUN_00087130(...,0x1194f010c,4,"Studio 1810c",...)` | observed in two independent artifacts |
| 0xA0 = 28-byte command packet, selectors 0x64/0x65/0x00 | kernel `mixer_s1810c.c:87-128`; UC `FUN_0007de30`/`FUN_0007ded0` call `0xA0` with (buf, len) | confirmed both sides |
| 0xA1/0xA2 state packet, seq in wValue, 252 bytes | kernel `mixer_s1810c.c:210-242`; UC `FUN_0007df80` uses `0xA1` then `0xA2` with the same incrementing u16 | confirmed both sides |
| state fields 58-62 = 48V/line/mute/mono/A-B | kernel `mixer_s1810c.c:163-167` | kernel-only, consistent with UC's `48V`/`Output Mute` parameter names |
| gain = 2^24 * 10^(dB/20) | kernel comment `mixer_s1810c.c:130-142` | kernel-only (capture-derived) |
| 0xA4 = clock status, wValue = src+1, 8 bytes | `dspusbdevice` `FUN_0007e0b0`; **observed live**, but only with interface recipient + wIndex 3 | observed, semantics unresolved |
| 0x42 = switch audio mode, wIndex 0/1 | `FUN_00081d50` -> `FUN_0009ed10(...,0x42,0,val,...)` | static only |
| 0xD0 write / 0xD1+0xD2 read DSP blob | `FUN_0007da50`, `FUN_0007dac0` | static; device stalls every shape tried |
| bulk frame header `u16 len+8, 0x01, 0x01, seq, pad` | `FUN_0007d4c0` stores `0x1010000`, then the u16 length, then a rolling byte at +4 | static only |
| bulk sizing/version via `0xC1` bRequest 1/0 | `FUN_0007ccd0`, `FUN_0007ce90` (recipient interface, type vendor) | static only |

"Static only" means: read out of the macOS binary, not yet reproduced against
the device. Treat those as hypotheses until a wire capture says otherwise.

## What is still unknown

1. **State packet fields 0-57.** 244 bytes of DSP state in a packed form. The
   tool prints them; the cheap experiment is two dumps with one control moved.
2. **DSP blob layout.** `blob` reads it. Then set one matrix cell to an
   unmistakable level (e.g. -20 dB = 0x0A2B5D0) and search the dump for that
   value; the surrounding stride/ids are the parameter map.
3. ~~How clock source is set~~ - **resolved on hardware.** It is plain UAC2:
   clock selector id 40 over sources 41/42/43 with `bmControls 0x03`, already
   exposed by the kernel as numid 3 (`PreSonus Clock Selector Clock Source`).
   The vendor `0xA4` request only adds per-source lock status. Still untested:
   what `0xA4` actually returns (blocked on usbfs permission).
4. **"Operation Mode" (Mixer/Interface)** and `SPDIF source`, `ADAT Channels
   Visible`, `Mirror Main to Mix n` from the UC UI. These parameter names exist
   in `studiousbdevice.dylib` but were not tied to a request; they are the most
   likely contents of the unknown state fields.
5. **Bulk channel** endpoint addresses and response framing.

## Live observations (device attached, 2026-11-27)

Enumerated as card 2 `S1810c`; `snd-usb-audio` bound to interfaces 0-4,
interface 5 (DFU) unclaimed. Current stream state: altset 2 -> 8 out / 14 in at
88.2/96 kHz, i.e. the 96 kHz profile, so `device_setup=0` is the kernel default.

Verified through the kernel's own implementation (not yet through ours, see
blocker below):

* set `numid=7` (Headphone 1 Source Route) 0 -> 1 -> 0 with `amixer`, value read
  back correctly each time. That is a full round trip of `0xA0` selector 0 /
  ctl 3 and state field 62 through the device, so the switch half of the
  protocol is confirmed against real hardware.
* `Line 1/2 Source Type` reads `Preamp Off (Line in)` on this unit.

Blocker: `/dev/bus/usb/003/015` is `root:root 0664`, the session user is not in
`root`, so pyusb cannot claim the EP0 channel. The udev rule in the repo fixes
it; it needs one sudo. Everything in section 2 of `PROTOCOL.md` marked
"static only" is still waiting on that.

Two static findings were corrected by the hardware:

* there is no vendor bulk interface on this box - interface 5 is DFU, and the
  only bulk pair belongs to the MIDI streaming interface;
* the interrupt endpoint on interface 0 (6 bytes / 16 ms) is the front-panel
  event channel that `FUN_000049b0` consumes, which no Linux driver reads.

## Note on the macOS-vs-Windows choice

The macOS app is the better target here, but not because it is "closer to Unix":
what mattered is that the DriverKit dext (`com.fender.tusbaudiodriver`) and the
daemon both carry the same Thesycon request layer with full type information in
C++ mangled names, and the pae SDK wrapper compiles down to one obvious
`IOUSBDevRequest` struct. A Windows build would have been equally usable and
would additionally have carried the WinUSB request wrappers, but this artifact
was the one in hand.
