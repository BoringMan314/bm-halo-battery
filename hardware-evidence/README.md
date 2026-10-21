# Hardware verification for PR #278

Date: 2026-10-21 (Asia/Taipei)

## White Sony INZONE H9

Connected as Sony INZONE H9, VID/PID `054C:0E53`, serial port COM6. The provider read successfully on both the PR worktree and the fork `main` worktree: `100%`, not charging, online.

The accompanying PCAP is filtered to the H9 serial interface endpoints only (`USBPcap3`, device address 3, endpoints `0x08` and `0x87`). It contains the live initialization and battery-query exchange. The battery response was:

```text
04 ff 0b 00 96 c3 14 04 10 01 00 00 64 e6
```

`0x64` is 100%; the frame matches the provider's battery-response signature and checksum.

## ASUS ROG Gladius III Wireless AimPoint

Connected through the ROG Omni Receiver (`0B05:1ACE`). The fork `main` provider read successfully: `100%`, not charging. Device reply:

```text
03 12 07 00 00 64 02 14 45 10 00 00
```

The PR branch intentionally excludes the Omni receiver implementation because that code is covered by the overlapping PR #185.

## Repeatability

The Sony provider was invoked independently from each worktree after closing HaloBattery and INZONE Hub to release COM6. Both returned an online 100% reading without diagnostics.

## Black Sony INZONE H9

Date: 2026-10-21 (Asia/Taipei). VID/PID `054C:0E53`, connected on COM3.

Live provider polls on the same black headset returned:

| Power state | Level | Charging | Online |
|---|---:|---|---|
| USB charging cable connected | 100% | yes | yes |
| USB charging cable unplugged | 100% | no | yes |

The unplugged poll was captured once with USBPcap. The accompanying
`sony-inzone-h9-black-unplugged-2026-10-21.pcap` is filtered to device address 2
and the H9 serial endpoints `0x08` and `0x87`; the raw capture was discarded after
filtering. Its battery query and response are:

```text
01 00 fc 08 96 c3 41 04 01 01 00 a0
04 ff 0b 00 96 c3 14 04 10 01 00 00 64 e6
```

The response has charging flag `0x00` at byte 11 and level `0x64` (100%) at byte 12.
The live provider returned `100%`, not charging, online, with no diagnostics. The
charging poll returned `charging=True`. 

## ASUS ROG Falchion RX Low Profile

Separate hardware check for the overlapping PR #185; this receiver support is not
included in PR #278. The ROG Omni receiver (`0B05:1ACE`) reported the paired keyboard
PID `1B06`. After waking, one query returned `83%`, not charging. With the keyboard
asleep, the receiver returned `02 ff aa`, which is treated as no battery reading.
After connecting the charging cable, one query returned `83%`, charging, confirming
both the battery and charging fields on this keyboard. The captured awake-state report
is in `asus-falchion-omni-2026-10-21.pcap`; its `12 01` reply begins:

```text
02 12 01 00 00 53 02 01 00 14 53 0d 10
```

The follow-up captures below correct the initial byte interpretation. The Falchion
parser update is on the fork's `main` branch; PR #278 remains limited to the INZONE H9
changes, as requested in the review.

The first awake capture was initially interpreted as 83% (`0x53`) from byte 5. That
interpretation is obsolete: the later live HIDAPI result shows byte 5 is a zero prefix,
and the provider no longer uses it as a battery level. The earlier PCAP is retained as
raw historical evidence only.

### ASUS ROG Falchion RX Low Profile, repeat capture while unavailable

Date: 2026-10-21 (Asia/Taipei). The installed HaloBattery diagnostic found the paired
keyboard on OMNI collection 2 and sent the same `02 12 01` battery query. The receiver
answered `02 ff aa`, so this poll had no battery value to decode. The earlier awake
capture on this same receiver did return 83%; the existing hardware check also observed
`ff aa` while the keyboard was asleep. This repeat therefore matches the known asleep or
unavailable response rather than a changed battery-report layout.

The filtered capture is `asus-falchion-omni-sleep-2026-10-21.pcap`. It contains the
receiver's interface-2 interrupt endpoints (`0x03` out and `0x83` in), including the
keyboard query and error reply. The diagnostic output also found the Gladius mouse
profile on the receiver, which returned `ff aa` during this poll.

### ASUS ROG Falchion RX Low Profile, awake reply

After the keyboard was woken, the old installed HaloBattery build incorrectly read
`0% charging` from this HIDAPI reply:

```text
02 12 01 00 00 00 54 02 01 00 14 54
```

The following USBPcap capture shows the successful response on the wire as
`02 12 01 00 00 54 02 01 00 14 54 36 10 ...`. It reports `0x54` (84%) and is not
charging: byte 8 is `00` on the wire. HaloBattery's HIDAPI result has an extra zero
before the level, so the duplicated level appears at bytes 6 and 11 and the charging
flag moves to byte 9 (`00`). The parser now reads those HIDAPI positions.

The filtered capture is `asus-falchion-omni-awake-2026-10-21.pcap` and contains the
receiver's interface-2 interrupt endpoints (`0x03` out and `0x83` in).

A fresh confirmation capture after the user confirmed the keyboard was not charging is
`asus-falchion-omni-current-2026-10-21.pcap`. Its reply is
`02 12 01 00 00 54 02 01 00 14 54 ...`: the level is 84%, and wire byte 8 is `00`
(not charging). The old installed build still reports `0% charging`; the updated source
parser reads the shifted HIDAPI fields instead.

### ASUS ROG Falchion RX Low Profile, charging

With the keyboard plugged in, a fresh live probe returned HIDAPI bytes
`02 12 01 00 00 00 54 02 01 01 14 54`: duplicated level bytes 6 and 11 are `0x54`
(84%), and byte 9 is `01` (charging). The corresponding USBPcap reply begins
`02 12 01 00 00 54 02 01 01 14 54 92 10 ...`; on the wire, the charging flag is byte 8.
The filtered capture is `asus-falchion-omni-plugged-2026-10-21.pcap`. The old installed
build still displays `0% charging` because it has not been rebuilt with the corrected
parser.
