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

The report id occupies byte 0 in hidapi's result, so the battery percentage is byte 5
(`0x53`, 83), and the charging flag is byte 8. Byte 11 changes between reports and is
not the percentage.
