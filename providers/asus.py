"""ASUS ROG / TUF wireless mice and OMNI receiver peripherals.

Source: G-Helper (seerge/g-helper, app/Peripherals/Mouse/AsusMouse.cs and the model
files in app/Peripherals/Mouse/Models). Only the protocol facts are used here (ids,
command, byte positions); the code is written for this app.

The exchange, on the vendor collection of interface 0 ("mi_00" in G-Helper):

    request   00 12 07          report id 0, command 12 07 (battery), zeros up to 65 bytes
    reply     00 12 07 ...      the echo of the command; after the report id:
                  byte 4        battery: a percentage, or a level 0..4 on older models
                  byte 9        charging when not 0
    error     00 ff aa ...      the mouse does not know the command
    zeros     00 00 00 ...      no reply (the mouse is off or asleep)

hidapi on Windows leaves out report id 0, so a reply starts with 12 07. A reply with
the report id in front is accepted too.

G-Helper takes a battery value of 0 without charging as "the mouse is in standby",
not as an empty battery. This provider does the same: no reading.

On the ROG OMNI receiver (0B05:1ACE), the ROG Gladius III Wireless AimPoint uses report
id 3 / collection 3 and the ROG Falchion RX Low Profile uses report id 2 / collection 2.
Both use 64-byte packets. Other OMNI-compatible ASUS models, the Harpe II Ace, Keris II
Ace / Origin, Harpe Ace Mini / Extreme, Strix Carry, Gladius II Wireless and MD200 are
not included.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

try:
    import hid
except ImportError:              # pragma: no cover
    hid = None

from . import hidlist
from .base import DeviceStatus, Provider, hexdump, log

ASUS_VID = 0x0B05
INTERFACE = 0
OMNI_PID = 0x1ACE
OMNI_INTERFACE = 2
OMNI_REPORT_ID = 0x03
OMNI_KEYBOARD_REPORT_ID = 0x02
OMNI_KEYBOARD_QUERY = [OMNI_KEYBOARD_REPORT_ID, 0x12, 0x01]

REQUEST = [0x00, 0x12, 0x07]         # report id 0, battery command
ECHO = (0x12, 0x07)
ERROR = (0xFF, 0xAA)
PACKET_LENGTH = 65                   # G-Helper's default packet size (report id + 64)
LEVEL_BYTE = 4                       # after the echo is found at 0 and 1
CHARGING_BYTE = 9

READ_TIMEOUT_MS = 300                # G-Helper's USB timeout
READ_ATTEMPTS = 8                    # other reports on the collection are skipped
WRITE_ATTEMPTS = 3

PERCENT, STEPS = 1, 25               # scale of the battery byte

# pid -> (name, scale). Wired and wireless pids of one mouse share the name, so they
# share one icon.
KNOWN: Dict[int, Tuple[str, int]] = {
    0x1A72: ("ROG Gladius III Aimpoint", PERCENT),
    0x1A70: ("ROG Gladius III Aimpoint", PERCENT),
    0x1B0C: ("ROG Gladius III Eva 2", PERCENT),
    0x1B0A: ("ROG Gladius III Eva 2", PERCENT),
    0x197F: ("ROG Gladius III Wireless", PERCENT),
    0x197D: ("ROG Gladius III Wireless", PERCENT),
    0x1A1A: ("ROG Chakram X", PERCENT),
    0x1A18: ("ROG Chakram X", PERCENT),
    0x1A94: ("ROG Harpe Ace Aim Lab Edition", PERCENT),
    0x1A92: ("ROG Harpe Ace Aim Lab Edition", PERCENT),
    0x1A68: ("ROG Keris Wireless Aimpoint", PERCENT),
    0x1A66: ("ROG Keris Wireless Aimpoint", PERCENT),
    0x1979: ("ROG Spatha X", PERCENT),
    0x1977: ("ROG Spatha X", PERCENT),
    0x19F4: ("TUF Gaming M4 Wireless", PERCENT),
    0x1A8D: ("TX Gaming Mouse", PERCENT),
    0x1AF5: ("TX Gaming Mouse Mini", PERCENT),
    0x1AF3: ("TX Gaming Mouse Mini", PERCENT),
    0x1C57: ("TUF Gaming Mini Miku Edition", PERCENT),
    0x1C56: ("TUF Gaming Mini Miku Edition", PERCENT),
    # older models: the battery byte is a level 0..4, G-Helper multiplies it by 25
    0x18E5: ("ROG Chakram", STEPS),
    0x18E3: ("ROG Chakram", STEPS),
    0x1960: ("ROG Keris Wireless", STEPS),
    0x195E: ("ROG Keris Wireless", STEPS),
    0x1A59: ("ROG Keris EVA Edition", STEPS),
    0x1A57: ("ROG Keris EVA Edition", STEPS),
    0x1908: ("ROG Pugio II", STEPS),
    0x1906: ("ROG Pugio II", STEPS),
    0x1949: ("ROG Strix Impact II Wireless", STEPS),
    0x1947: ("ROG Strix Impact II Wireless", STEPS),
}

Reading = Tuple[int, bool, str]     # level %, charging, approximate text ("" = exact)


def parse_omni_keyboard_reply(r: List[int]) -> Optional[Tuple[int, bool]]:
    """Parse an OMNI Falchion 12 01 reply -> (battery percent, charging)."""
    if len(r) < 12 or r[0] != OMNI_KEYBOARD_REPORT_ID or r[1:3] != [0x12, 0x01]:
        return None
    # On the current receiver/hidapi path an extra zero shifts the wire fields by one:
    # level is duplicated at bytes 6 and 11, and charging is byte 9. Byte 5 is a
    # zero prefix, not the battery level.
    level, charging = r[6], r[9] == 1
    if level != r[11]:
        return None
    if level > 100 or (level == 0 and not charging):
        return None
    return level, charging


def _offset(r: List[int], pair: Tuple[int, int]) -> Optional[int]:
    """Where `pair` starts in a reply: 0 (hidapi left out report id 0), or 1 (report
    id 0 or 3 in front). None when the reply does not start with it."""
    if len(r) > 1 and (r[0], r[1]) == pair:
        return 0
    if len(r) > 2 and r[0] in (0x00, OMNI_REPORT_ID) and (r[1], r[2]) == pair:
        return 1
    return None


def has_echo(r: List[int]) -> bool:
    return _offset(r, ECHO) is not None


def is_error(r: List[int]) -> bool:
    return _offset(r, ERROR) is not None


def parse_reply(r: List[int], scale: int) -> Optional[Reading]:
    """A reply that echoes 12 07 -> (level, charging, text). None for anything else,
    for the standby value (0 and not charging) and for a value out of range."""
    m = _offset(r, ECHO)
    if m is None or len(r) < m + CHARGING_BYTE + 1:
        return None
    raw = r[m + LEVEL_BYTE]
    charging = r[m + CHARGING_BYTE] != 0
    if raw == 0 and not charging:
        return None                                  # standby, not empty
    if scale == STEPS:
        if raw > 4:
            return None
        level = raw * STEPS
        text = f"about {level}%" + (", charging" if charging else "")
        return level, charging, text
    if raw > 100:
        return None
    return raw, charging, ""


class AsusProvider(Provider):
    name = "asus"

    def __init__(self):
        self._diag: List[str] = []
        self._failing: Dict[str, bool] = {}

    def _read(self, path, scale: int, report_id: int = 0x00,
              packet_length: int = PACKET_LENGTH) -> Optional[Reading]:
        request = [report_id, 0x12, 0x07]
        dev = hid.device()
        try:
            dev.open_path(path)
        except (OSError, IOError) as e:
            self._diag.append(f"    open: {e}")
            return None
        try:
            # drop reports that are already waiting, as G-Helper does before a request
            try:
                dev.set_nonblocking(True)
                for _ in range(16):
                    if not dev.read(packet_length):
                        break
                dev.set_nonblocking(False)
            except (OSError, IOError, ValueError):
                pass
            for _ in range(WRITE_ATTEMPTS):
                try:
                    dev.write(request + [0x00] * (packet_length - len(request)))
                except (OSError, IOError, ValueError) as e:
                    self._diag.append(f"    write: {e}")
                    return None
                for _ in range(READ_ATTEMPTS):
                    r = list(dev.read(packet_length, READ_TIMEOUT_MS) or [])
                    if not r:
                        break                        # timeout: send the request again
                    if is_error(r):
                        self._diag.append(f"    reply: error {hexdump(r, 12)}")
                        return None
                    if not any(r):
                        self._diag.append("    reply: all zeros (off or asleep)")
                        return None
                    if not has_echo(r):
                        continue                     # a button or profile event: skip it
                    self._diag.append(f"    reply: {hexdump(r, 12)}")
                    res = parse_reply(r, scale)
                    if res is None:
                        self._diag.append("    battery 0 and not charging (standby), or out of range")
                    return res
            self._diag.append("    no reply with the 12 07 echo")
            return None
        finally:
            try:
                dev.close()
            except Exception:
                pass

    def _read_omni_keyboard(self, path) -> Optional[Tuple[int, bool]]:
        """Read the Falchion RX Low Profile battery from OMNI collection 2."""
        packet_length = 64
        dev = hid.device()
        try:
            dev.open_path(path)
        except (OSError, IOError) as e:
            self._diag.append(f"    open: {e}")
            return None
        try:
            try:
                dev.set_nonblocking(True)
                for _ in range(16):
                    if not dev.read(packet_length):
                        break
                dev.set_nonblocking(False)
            except (OSError, IOError, ValueError):
                pass
            for _ in range(WRITE_ATTEMPTS):
                try:
                    dev.write(OMNI_KEYBOARD_QUERY + [0x00] * (packet_length - 3))
                except (OSError, IOError, ValueError) as e:
                    self._diag.append(f"    write: {e}")
                    return None
                for _ in range(READ_ATTEMPTS):
                    r = list(dev.read(packet_length, READ_TIMEOUT_MS) or [])
                    if not r:
                        break
                    if len(r) >= 3 and r[0] == OMNI_KEYBOARD_REPORT_ID and r[1:3] == [0xFF, 0xAA]:
                        self._diag.append(f"    reply: error {hexdump(r, 12)}")
                        return None
                    if not any(r):
                        self._diag.append("    reply: all zeros (off or asleep)")
                        return None
                    if len(r) < 3 or r[0] != OMNI_KEYBOARD_REPORT_ID or r[1:3] != [0x12, 0x01]:
                        continue
                    self._diag.append(f"    reply: {hexdump(r, 12)}")
                    reading = parse_omni_keyboard_reply(r)
                    if reading is None:
                        self._diag.append("    battery 0 and not charging (standby), or out of range")
                        return None
                    return reading
            self._diag.append("    no reply with the 12 01 echo")
            return None
        finally:
            try:
                dev.close()
            except Exception:
                pass

    def poll(self) -> List[DeviceStatus]:
        self._diag = []
        if hid is None:
            return []
        try:
            infos = hidlist.enumerate(ASUS_VID)
        except Exception as e:  # pragma: no cover
            log.warning("hid.enumerate(asus): %s", e)
            return []

        found: Dict[str, Reading] = {}
        keyboard_reading: Optional[Tuple[int, bool]] = None
        for d in infos:
            pid = d["product_id"]
            path = d.get("path", b"")
            path_text = path.decode("latin-1", "ignore") if isinstance(path, bytes) else str(path)
            if (pid == OMNI_PID and d.get("interface_number") == OMNI_INTERFACE
                    and "&col03" in path_text.lower()):
                # G-Helper identifies Gladius III AimPoint on OMNI via MI_02&Col03.
                # Match the collection path exactly; the receiver also exposes other
                # vendor collections used by its buttons and other paired peripherals.
                name = "ROG Gladius III Wireless AimPoint"
                self._diag.append(f"[ASUS] {name} via OMNI pid={pid:04x} usage="
                                  f"{d.get('usage_page', 0):04x}:{d.get('usage', 0):04x}")
                res = self._read(d["path"], PERCENT, OMNI_REPORT_ID, 64)
                if res is None:
                    continue
                self._diag.append(f"  -> {res[2] or str(res[0]) + '%'}{' charging' if res[1] else ''}")
                if name not in found or (res[1] and not found[name][1]):
                    found[name] = res
                continue
            # Falchion RX Low Profile is the second peripheral profile on OMNI.
            # G-Helper identifies it on MI_02&Col02 with report id 2.
            if (pid == OMNI_PID and d.get("interface_number") == OMNI_INTERFACE
                    and "&col02" in path_text.lower()):
                name = "ROG Falchion RX Low Profile"
                self._diag.append(f"[ASUS] {name} via OMNI pid={pid:04x} usage="
                                  f"{d.get('usage_page', 0):04x}:{d.get('usage', 0):04x}")
                res = self._read_omni_keyboard(d["path"])
                if res is not None:
                    keyboard_reading = res
                    self._diag.append(f"  -> {res[0]}%{' charging' if res[1] else ''}")
                continue
            if pid not in KNOWN:
                continue
            if d.get("interface_number") != INTERFACE or d.get("usage_page", 0) < 0xFF00:
                continue                                 # only the vendor collection
            name, scale = KNOWN[pid]
            self._diag.append(f"[ASUS] {name} pid={pid:04x} usage="
                              f"{d.get('usage_page', 0):04x}:{d.get('usage', 0):04x}")
            res = self._read(d["path"], scale)
            if res is None:
                continue
            self._diag.append(f"  -> {res[2] or str(res[0]) + '%'}{' charging' if res[1] else ''}")
            # the same mouse on the cable and on the receiver: keep the charging reading
            if name not in found or (res[1] and not found[name][1]):
                found[name] = res

        out: List[DeviceStatus] = []
        for name, (level, charging, text) in found.items():
            key = "asus:" + name.lower().replace(" ", "-")
            out.append(DeviceStatus(key, name, level, charging, True, "asus", text, kind="mouse",
                                    ui_message="state.approx" if text else "",
                                    ui_params={"level": level, "charging": charging} if text else {}))
        if keyboard_reading is not None:
            level, charging = keyboard_reading
            out.append(DeviceStatus("asus:rog-falchion-rx-low-profile",
                                    "ROG Falchion RX Low Profile", level, charging, True,
                                    "asus", kind="keyboard"))
        return out

    def diagnostics(self) -> List[str]:
        return list(self._diag)
