# Studio 1810c vendor USB protocol

USB id **194f:010c**, model id **0x1_194f_010c** ("Studio 1810c", device family 4,
codename *Demeter*) in Universal Control's device table.

Everything below is a **vendor control transfer** (recipient = device) unless a
line says otherwise, so it works on EP0 while `snd-usb-audio` owns the streaming
interfaces. Little-endian throughout.

## 1. Transfer frame

Universal Control's macOS code builds an `IOUSBDevRequest`-shaped struct and
issues it through the Thesycon/pae SDK wrapper
(`dspusbdevice.dylib` `FUN_00096030` = OUT, `FUN_00095f50` = IN):

```
u8  bmRequestType = dir | (type << 5) | recipient   ; type 2 = vendor
u8  bRequest
u16 wValue
u16 wIndex
u16 wLength
void *pData
u32 lenDone
u32 noDataTimeout
```

Most requests use recipient 0 (device). **The device is fussy about this:** on
firmware 5.1.1 `0xA4` and several others stall with EPIPE unless addressed to
recipient 1 (interface) with wIndex 3, the legacy UAC1.0 control interface.
Verified shapes are noted per request below.

## 2. Request map

| bmRequestType | bRequest | direction | wValue | length | meaning | source |
|---|---|---|---|---|---|---|
| 0x40 | `0xA0` | OUT | 0 | 28 | command packet (mixer cell / output fader / device switch) | kernel `mixer_s1810c.c`, `dspusbdevice` `FUN_0007de30` |
| 0x40 | `0xA1` | OUT | seq | 252 | write state packet before reading | kernel, `FUN_0007df80` |
| 0xC0 | `0xA2` | IN  | seq | 252 | read state packet (same seq) | kernel, `FUN_0007df80` |
| 0xC1 | `0xA4` | IN  | clock source + 1 (1..3) | 8 | clock status, **wIndex 3 required**; observed `00000000000b0000` for all three sources (value 0, byte 4 = 0, byte 5 = 0x0b - meaning unresolved) | `FUN_0007e0b0` |
| 0x40 | `0x42` | OUT | 0 | 0 | switch audio mode, wIndex = 0 or 1 (Studio family) | `FUN_00081d50` |
| 0xC0 | `0x43` | IN  | 0x0AFF + src*0x100 | 8 | clock status, other families (not the 1810c) | `FUN_00082570` |
| 0xC0 | `0xB1` | IN  | 0 | 2 | 2-byte family status word | `FUN_0007dc30` |
| 0x40 | `0xD0` | OUT | 0 | n | write DSP parameter blob | `FUN_0007da50`, `FUN_0007de30` |
| 0x40 | `0xD1` | OUT | seq | n | DSP blob read, request half | `FUN_0007dac0` |
| 0xC0 | `0xD2` | IN  | seq | n | DSP blob read, answer half | `FUN_0007dac0` |
| 0xC0 | `0xD4` | IN  | 10..13 | 8 | per-index status (value + flag byte 4) | `FUN_0007dcc0` |
| 0xC1 | `0x01` | IN  | 0 = max command len, 1 = max response len | 4 | bulk channel sizing (interface recipient, wIndex = iface) | `FUN_0007ccd0` |
| 0xC1 | `0x00` | IN  | 0 | 2 | bulk protocol version, must be 1.x | `FUN_0007ce90` |

`seq` is a 16-bit counter that increments per transaction (skipping 0xFFFF); the
device only answers `0xA2`/`0xD2` with the sequence number of the preceding
`0xA1`/`0xD1`. The kernel starts at 1.

## 3. Command packet (`0xA0`, 28 bytes, 7 x u32)

```
u32 selector
u32 b
u32 tag      = 0x50617269  ("Pari")
u32 length   = 0x14
u32 c
u32 d
u32 e
```

### selector 0x64 - mixer matrix
`b` = input channel (0-35), `c` = output pair (0-8), `d` = 0 left / 1 right,
`e` = gain.

```
inputs  0-7 analog, 8-9 S/PDIF, 10-17 ADAT 1-8, 18-35 DAW 1-18
pairs   0 Main, 1 Line 1/2, 2 Line 3/4, 3 S/PDIF, 4-8 (ADAT pairs, 1824c)
```

### selector 0x65 - output fader
`b` = output pair, `c` = 0, `d` = side, `e` = gain.

### selector 0x00 - device switch
`d` = control id, `e` = value (0/1). Known ids:

```
0 line  (preamp on = mic/inst, off = line in)
1 mute  (main out)
2 mono  (1824c only)
3 A/B   (headphone 1 source: 0 = 1/2, 1 = 3/4)
4 48V   (phantom power on mic inputs)
```

### gain encoding
```
raw = 2**24 * 10**(dB / 20)      0 dB = 0x01000000     -inf / mute = 0
-96 dB ~ 0x109      -3 dB ~ 0xb53bf0      slider range -96 .. +10 dB
```
A stereo-panned channel is written at slider value minus 3 dB, hence the
`-99 dB` values visible in captures.

## 4. State packet (`0xA1` / `0xA2`, 252 bytes = 63 x u32)

The buffer is zeroed except:

```
fields[2] = 0x64656D73  ("dems")
fields[3] = 0xF4
```

**`fields[0]` must stay 0.** The sequence lives only in wValue; putting it in
fields[0] makes the device stall the SET with EPIPE (found on hardware, cost one
debugging round). Same for a 244-byte transfer: 252 works, 244 works, but the
packet content is what the device validates, not the length.

Write it with `0xA1`, then read it back with `0xA2` using the *same* wValue.
Fields 58-62 are the switch states the Linux kernel exposes:

```
[58] 48V   [59] line   [60] mute   [61] mono (1824c)   [62] headphone A/B
```

Measured on hardware (5.1.1, idle + tone):

```
fields 4..11   eight values that fluctuate every read (0x4f00 .. 0x31a00).
               They do NOT follow a 1 kHz tone through the matrix and do not
               drop when DAW->Main is muted, so they are not output meters;
               likely input meters with an offset, or free-running counters.
fields 46, 47  constant 0x100 (256) - rate/mode index, unresolved.
fields 48..57  constant 0
fields 58..62  switch states, verified live (see below)
```

Switch fields were verified in both directions: writing `0xA0` selector 0 /
ctl 3 (A/B) and ctl 0 (line) with this tool changes fields 62 and 59, and the
kernel's own ALSA controls - which read those same fields - follow immediately.
`uc1810c.py verify` reproduces that check.

Note the kernel sends 252 bytes while the in-packet length field says 0xF4 (244).
Keep the 252-byte transfer: that is what the shipped kernel does and what the
device accepts.

## 5. DSP parameter channel (`0xD0` / `0xD1` + `0xD2`)

Universal Control's real mixer model (channel names, colours, pans, solos,
preset blobs) is not built from the 0xA0 packet stream; it is a parameter blob:

* **write**: `0xD0` OUT with the blob, wValue 0, no read-back.
* **read**: `0xD1` OUT (sequence in wValue, buffer length n), then `0xD2` IN with
  the same sequence and length. The read frame the host sends is all zeros.

`FUN_0007df80` is the same pattern wrapped with a model check that rejects
device `0x1_194f_0108` (Studio 24) with `DspParameterInterface not supported`.

Blob layout: unknown. Suggested next step is empirical - write a distinctive
matrix level through `0xA0`, then scan a `blob` dump for that raw value to find
the cell offsets, and diff dumps while toggling one control at a time.

## 6. Bulk command channel

**Constraint found on real hardware:** the 1810c exposes exactly one bulk pair,
on the MIDI-Streaming interface (4): EP `0x02` OUT / `0x84` IN, 512-byte packets.
There is no separate vendor bulk interface (interface 5 is DFU, no endpoints).
So UC's `OpenBulkSubdevice` either reuses the MIDI pipe or the device
re-enumerates after a `0x42` mode switch. On Linux `snd-usb-audio` claims
interface 4, so a Linux implementation has to go through the rawmidi node
(`/dev/snd/midiC2D0`) or unbind the MIDI driver first.

A second, packetised command path exists on a bulk endpoint pair (used for
larger transactions). Recovery from `FUN_0007d4c0` (`SendCommand`) and
`FUN_0007c560` (`OpenBulkCmdDevice`):

```
frame: u16 totalLength (= payload + 8)
       u8  0x01
       u8  0x01
       u8  sequence (rolling, 1..255)
       u8  0
       u8  0
       u8  0
       payload ...
```

Bring-up order: claim the command interface -> `0xC1/0x00` protocol version must
be `1.x` -> `0xC1/0x01` wValue 0 for max command length and wValue 1 for max
response length -> open bulk OUT/IN pipes -> `SendCommand` writes a frame and
waits for the bulk IN response.

Not implemented here; the control-transfer path already covers routing, faders
and switches, which is what the kernel leaves out.

## 6b. Requests the device refuses (5.1.1, from usbfs)

Swept every recipient x wIndex shape that made sense:

```
0x42 (audio mode)    stalls in all shapes: dev/if0/if3, wValue 0/1, len 0
0xB1 (status word)   stalls: dev/if0/if1/if2/if3/if4, len 2/4/8
0xD0-0xD2 (DSP)      stalls: OUT 0xD1 stalls for len 8/64/244/256, so the
                     read half never gets a chance
0xD4                 stalls: dev/if3, wValue 10..13
```

Only `0xA0`, `0xA1`/`0xA2`, and `0xA4` (on interface 3) answer. Two plausible
explanations, both untested: these belong to the bulk/DSP stack that is gated
behind the audio-mode switch (`0x42`), or they need the interface claimed via
usbfs (which on Linux means detaching `snd-usb-audio`). Since the matrix and all
switches already work over `0xA0`, this is not on the critical path - it only
costs the ability to read the matrix back.

## 7. Physical interface map (live, `lsusb -v`)

```
iface 0  Audio Control (UAC2)           1 interrupt EP 0x83 IN, 6 bytes / 16 ms
iface 1  Audio Streaming (playback)     iso 0x01 OUT + 0x81 IN, 4 altsets
iface 2  Audio Streaming (capture)      iso 0x82 IN, 4 altsets
iface 3  Audio Control (UAC1.0 legacy)  no endpoints
iface 4  MIDI Streaming                 bulk 0x02 OUT + 0x84 IN, 512 B
iface 5  DFU (class FE / sub 1 / pr 1)  no endpoints, wTransferSize 64
```

Consequences:

* **Interrupt EP 0x83** is the device pushing button/state events to the host;
  it matches the flag-byte consumer at `dspusbdevice` `FUN_000049b0`
  (bits at packet offsets 0xB8/0xB9 driving mute, line, A/B and the four
  channel switches). Nothing in Linux listens to it today.
* **Interface 5 is firmware update.** Leave it alone unless flashing.
* **Clock source is plain UAC2**, not vendor: clock selector id 40 with three
  sources (41 internal, 42 S/PDIF, 43 ADAT), `bmControls 0x03` = read/write.
  `amixer -D hw:2 cget numid=3` already reads and sets it. The `0xA4` request
  only adds per-source lock status, which UAC2 does not expose.

## 8. Device table

Recovered from the model table in `dspusbdevice.dylib` (`FUN_0006f760`),
`0x1_<vid>_<pid>` -> (family, name):

```
0104 Studio 26      0105 Studio 68      0106 Studio 1810    0107 Studio 1824
0108 Studio 24      0109 Studio 24c     010a Studio 26c     010b Studio 68c
010c Studio 1810c   010d Studio 1824c
0208 ioStation 24c
0601 Studio 192 (Artemis)   0603 Studio 192 Mobile (Artemis Jr)
0701..0707 StudioLive AR16/AR12/AR8/A22/AR8c/AR12c/AR16c
0801..0820 StudioLive 32/16/24/24R/16R/32R/64/32S/32SX/32SC (+SE, +reduced)
0901 StudioLive 16.0.2 USB
0100..0103 AudioBox 22VSL/44VSL/1818VSL   0301..0303 AudioBox USB / USB 96
0401/0403 AudioBox iOne/iTwo   040b AudioBox Go
```

Family numbers seen in the same table: 1 AudioBox, 2 Artemis, 3 StudioLive AR,
4 Demeter (= Studio series incl. 1810c), 5 StudioLive AI, 8 SLClassic,
9 ioStation.
