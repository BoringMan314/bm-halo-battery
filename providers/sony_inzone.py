"""Read the battery of Sony INZONE H9/H7 headsets through their USB dongle.

The battery interface is a USB serial interface (VID/PID 054C:0E53).
INZONE Hub may hold the serial COM port, so a concurrent session is reported as
busy instead of interrupting it.

The packet sequence and response layout follow the observations published by
janit88/InZoneH9Tray. Hardware confirmation in Halo Battery is still pending.
"""
from __future__ import annotations

import time
from typing import List, Optional

from . import hidlist

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - requirements install pyserial
    serial = None
    list_ports = None

from .base import DeviceStatus, Provider

VID = 0x054C
PID = 0x0E53
HID_PID = 0x0E4C
NAME = "Sony INZONE H9"

INIT_1 = bytes.fromhex("01 00 FC 08 96 C3 21 01 01 01 00 7D")
INIT_2 = bytes.fromhex("01 00 FC 08 96 C3 41 02 01 01 00 9E")
BATTERY_QUERY = bytes.fromhex("01 00 FC 08 96 C3 41 04 01 01 00 A0")
BATTERY_SIGNATURE = bytes.fromhex("04 FF 0B 00 96 C3 14 04")
FRAME_LENGTH = 14


def find_battery_frame(data: bytes) -> Optional[bytes]:
    """Return a well-formed 14-byte battery response from a serial read."""
    for offset in range(max(0, len(data) - FRAME_LENGTH + 1)):
        frame = data[offset:offset + FRAME_LENGTH]
        if (frame.startswith(BATTERY_SIGNATURE)
                and frame[11] in (0, 1) and frame[12] <= 100):
            return frame
    return None


class SonyInzoneProvider(Provider):
    name = "sony_inzone"

    def __init__(self):
        self._diag: List[str] = []

    @staticmethod
    def _ports():
        if list_ports is None:
            return []
        return [port for port in list_ports.comports()
                if port.vid == VID and port.pid == PID]

    @staticmethod
    def _read_for(port, seconds: float = 0.8) -> bytes:
        data = bytearray()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            waiting = port.in_waiting
            chunk = port.read(waiting if waiting else 1)
            if chunk:
                data.extend(chunk)
        return bytes(data)

    @classmethod
    def _send_and_read(cls, port, command: bytes) -> bytes:
        port.write(command)
        time.sleep(0.25)
        return cls._read_for(port)

    def _read(self, port_info) -> Optional[DeviceStatus]:
        try:
            with serial.Serial(
                    port=port_info.device, baudrate=115200, bytesize=8,
                    parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                    timeout=0.2, write_timeout=1, xonxoff=False,
                    rtscts=False, dsrdtr=False) as port:
                port.dtr = True
                port.rts = True
                time.sleep(0.5)
                port.reset_input_buffer()
                port.reset_output_buffer()
                self._send_and_read(port, INIT_1)
                self._send_and_read(port, INIT_2)
                response = self._send_and_read(port, BATTERY_QUERY)
        except (OSError, serial.SerialException) as exc:
            message = str(exc)
            busy = any(word in message.lower() for word in
                       ("access is denied", "permission", "in use", "busy"))
            self._diag.append(f"  {port_info.device}: {'busy' if busy else 'serial error'}: {message}")
            return None

        frame = find_battery_frame(response)
        if frame is None:
            self._diag.append(f"  {port_info.device}: no battery response; "
                              "INZONE Hub may be using the port")
            return None

        self._diag.append(f"  {port_info.device}: reply " +
                          " ".join(f"{byte:02x}" for byte in frame))
        return DeviceStatus(
            key="sony_inzone_h9", name=NAME, level=frame[12],
            charging=(frame[11] == 1), online=True,
            source=self.name, kind="headset")

    def poll(self) -> List[DeviceStatus]:
        self._diag = []
        if serial is None or list_ports is None:
            self._diag.append("[Sony INZONE] pyserial is unavailable")
        else:
            ports = self._ports()
            if ports:
                self._diag.append(f"[Sony INZONE] VID={VID:04x} PID={PID:04x}, "
                                  f"{len(ports)} serial port(s)")
                for port in ports:
                    status = self._read(port)
                    if status is not None:
                        return [status]

        # The 0E4C receiver seen in diagnostics exposes HID collections but no
        # writable battery channel. Point the user at the transceiver's PC mode
        # rather than sending an unverified command to an unrelated collection.
        try:
            alternate = [d for d in hidlist.enumerate(VID)
                         if d.get("product_id") == HID_PID]
        except Exception as exc:
            self._diag.append(f"[Sony INZONE] HID enumeration failed: {exc}")
            alternate = []
        if alternate:
            self._diag.append(
                f"[Sony INZONE] 054c:{HID_PID:04x} HID receiver detected without "
                f"a 054c:{PID:04x} battery COM port; check that the transceiver "
                "switch is set to PC mode.")
        return []

    def diagnostics(self) -> List[str]:
        return list(self._diag)
