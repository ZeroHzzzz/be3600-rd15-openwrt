#!/usr/bin/env python3
"""1.8 V serial console for the RD15: timestamped capture + line-mode typing.

Modes
  interactive (default)  print everything that arrives, type a line + Enter to send
  --send "cmd" ...       send the given lines, then keep listening until --idle seconds pass
  --listen SECONDS       capture only, exit after SECONDS of silence

Everything received is appended to a log file (default: serial-YYYYmmdd-HHMMSS.log)
so the boot log, U-Boot env and any panic stay readable afterwards.

NOTE: the RD15 console is 1.8 V logic. Never connect a 3.3 V/5 V adapter, VCC,
or the unidentified 4th pad.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import threading
import time

import serial


class Logger:
    def __init__(self, path: str) -> None:
        self.path = path
        self.fh = open(path, "a", buffering=1, encoding="utf-8", errors="replace")
        self.lock = threading.Lock()

    def write(self, text: str) -> None:
        with self.lock:
            self.fh.write(text)
            sys.stdout.write(text)
            sys.stdout.flush()


def reader(port: serial.Serial, log: Logger, stop: threading.Event, idle: float | None) -> None:
    last = time.monotonic()
    buf = b""
    while not stop.is_set():
        try:
            chunk = port.read(port.in_waiting or 1)
        except serial.SerialException as exc:
            log.write(f"\n[serial error] {exc}\n")
            stop.set()
            return
        if chunk:
            last = time.monotonic()
            buf += chunk
            # Split out partial UTF-8 lines but never hide bytes: decode leniently.
            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                stamp = dt.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                log.write(f"[{stamp}] " + line.decode("utf-8", "replace").rstrip("\r") + "\n")
        else:
            if buf:
                stamp = dt.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                log.write(f"[{stamp}] " + buf.decode("utf-8", "replace") + "\n")
                buf = b""
            if idle is not None and time.monotonic() - last > idle:
                stop.set()
                return
            time.sleep(0.01)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--log", default=None, help="log path (default serial-<stamp>.log)")
    ap.add_argument("--send", nargs="*", default=None, help="lines to send before listening")
    ap.add_argument("--delay", type=float, default=0.4, help="delay between --send lines")
    ap.add_argument("--listen", type=float, default=None, help="exit after N seconds of silence")
    ap.add_argument("--idle", type=float, default=None, help="with --send: exit after N idle seconds")
    args = ap.parse_args()

    log_path = args.log or dt.datetime.now().strftime("serial-%Y%m%d-%H%M%S.log")
    if not os.path.exists(args.port):
        print(f"no such port: {args.port} (adapter plugged in?)", file=sys.stderr)
        return 2

    port = serial.Serial(args.port, args.baud, bytesize=8, parity="N", stopbits=1,
                         timeout=0.05, exclusive=True)
    log = Logger(log_path)
    log.write(f"\n===== session {dt.datetime.now().isoformat(timespec='seconds')} "
              f"{args.port} {args.baud} 8N1 =====\n")

    stop = threading.Event()
    idle = args.listen if args.listen is not None else (args.idle if args.send is not None else None)
    th = threading.Thread(target=reader, args=(port, log, stop, idle), daemon=True)
    th.start()

    try:
        if args.send is not None:
            for line in args.send:
                log.write(f">>> {line}\n")
                port.write(line.encode() + b"\r")
                port.flush()
                time.sleep(args.delay)
            log.write("(now capturing; Ctrl-C to stop)\n")
        else:
            log.write("(type a line + Enter to send, Ctrl-C to stop)\n")
        while not stop.is_set():
            if args.send is not None:
                time.sleep(0.05)
                continue
            line = sys.stdin.readline()
            if line == "":
                time.sleep(0.05)
                continue
            text = line.rstrip("\n")
            port.write(text.encode() + b"\r")
            port.flush()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        th.join(timeout=1.0)
        port.close()
        log.write(f"===== end {dt.datetime.now().isoformat(timespec='seconds')} =====\n")
        print(f"\n[log: {log_path}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
