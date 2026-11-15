#!/usr/bin/env python3
"""Drive the RD15 stock U-Boot: set network, TFTP the initramfs, boot it in RAM.

Nothing here writes flash. It only sets volatile env vars, downloads the
initramfs into RAM and calls bootm.

  python3 ram_boot.py --port /dev/ttyACM0 --server 192.168.31.100 \
      --file openwrt-qualcommbe-ipq53xx-xiaomi_rd15-initramfs-uImage.itb \
      --addr 0x47000000
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time

import serial

PROMPT = "IPQ5332#"


class Console:
    def __init__(self, port: str, baud: int, log_path: str) -> None:
        self.p = serial.Serial(port, baud, timeout=0.05,
                               bytesize=8, parity="N", stopbits=1)
        self.log = open(log_path, "w", buffering=1, encoding="utf-8", errors="replace")
        self.buf = ""

    def emit(self, text: str) -> None:
        self.log.write(text)
        sys.stdout.write(text)
        sys.stdout.flush()

    def drain(self, seconds: float) -> str:
        end = time.monotonic() + seconds
        out = ""
        while time.monotonic() < end:
            chunk = self.p.read(self.p.in_waiting or 1)
            if chunk:
                text = chunk.decode("utf-8", "replace")
                out += text
                self.emit(text)
                end = time.monotonic() + seconds
        return out

    def send(self, cmd: str) -> None:
        self.emit(f"\n>>> {cmd}\n")
        self.p.write(cmd.encode() + b"\r")
        self.p.flush()

    def wait_for(self, pattern: str, timeout: float) -> tuple[bool, str]:
        rx = re.compile(pattern)
        end = time.monotonic() + timeout
        out = ""
        while time.monotonic() < end:
            chunk = self.p.read(self.p.in_waiting or 1)
            if chunk:
                text = chunk.decode("utf-8", "replace")
                out += text
                self.emit(text)
                if rx.search(out):
                    return True, out
        return False, out

    def close(self) -> None:
        self.p.close()
        self.log.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--ip", default="192.168.31.200")
    ap.add_argument("--server", default="192.168.31.100")
    ap.add_argument("--file", default="openwrt-qualcommbe-ipq53xx-xiaomi_rd15-initramfs-uImage.itb")
    ap.add_argument("--addr", default="0x47000000")
    ap.add_argument("--config", default="config@mi04.1-c2")
    ap.add_argument("--log", default=None)
    ap.add_argument("--download-only", action="store_true")
    ap.add_argument("--wait", action="store_true",
                    help="router is powered off: wait for power-on and catch the countdown")
    ap.add_argument("--reboot", action="store_true",
                    help="the stock shell is running: reset it first and catch the countdown")
    args = ap.parse_args()

    log_path = args.log or dt.datetime.now().strftime("ramboot-%Y%m%d-%H%M%S.log")
    c = Console(args.port, args.baud, log_path)
    c.emit(f"===== ram_boot {dt.datetime.now().isoformat(timespec='seconds')} "
           f"addr={args.addr} server={args.server} =====\n")
    try:
        # 1. get to the prompt (the boot countdown is interruptible)
        ok = False
        if args.wait:
            start = time.monotonic()
            while time.monotonic() - start < 240:
                ok, _ = c.wait_for(re.escape(PROMPT), 0.5)
                if ok:
                    break
                c.p.write(b"\r")
            if not ok:
                print("\n[FAIL] no bootloader prompt after power-on", file=sys.stderr)
                return 2
        elif args.reboot:
            c.send("reboot")
            start = time.monotonic()
            while time.monotonic() - start < 150:
                ok, _ = c.wait_for(re.escape(PROMPT), 0.5)
                if ok:
                    break
                c.p.write(b"\r")   # any key interrupts the 15 s countdown
            if not ok:
                print("\n[FAIL] did not reach the bootloader prompt", file=sys.stderr)
                return 2
        else:
            for _ in range(3):
                c.p.write(b"\r")
                ok, _ = c.wait_for(re.escape(PROMPT), 1.5)
                if ok:
                    break
        if not ok:
            print("\n[FAIL] U-Boot prompt not found", file=sys.stderr)
            return 2
        c.drain(0.5)

        # 2. volatile network settings only
        for cmd in (f"setenv ipaddr {args.ip}",
                    f"setenv serverip {args.server}",
                    "setenv netmask 255.255.255.0"):
            c.send(cmd)
            c.wait_for(re.escape(PROMPT), 3)

        # 3. link check
        c.send(f"ping {args.server}")
        alive, out = c.wait_for(r"is alive|not alive|ping failed|ARP Retry", 12)
        if not alive or "not alive" in out or "ping failed" in out:
            print("\n[FAIL] no link to the TFTP server", file=sys.stderr)
            return 3
        print("\n[OK] link is up")

        # 4. download
        c.send(f"tftpboot {args.addr} {args.file}")
        got, out = c.wait_for(r"Bytes transferred|TFTP error|Retry count exceeded|not found", 90)
        if not got or "Bytes transferred" not in out:
            print("\n[FAIL] tftp download", file=sys.stderr)
            return 4
        print("\n[OK] image is in RAM")

        if args.download_only:
            return 0

        # 5. boot it
        c.send(f"bootm {args.addr}#{args.config}")
        c.drain(25)
        print(f"\n[done] log: {log_path}")
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
