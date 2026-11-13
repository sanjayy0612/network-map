"""Small keyboard-driven terminal view for a network scan."""

from __future__ import annotations

import curses
import json
from datetime import datetime, timezone
from pathlib import Path

from .cli import scan, write_html


def save_report(network: str, gateway: str | None, devices: list[dict[str, str | None]],
                json_path: str, html_path: str) -> None:
    report = {"network": network, "gateway": gateway,
              "scanned_at": datetime.now(timezone.utc).isoformat(), "devices": devices}
    Path(json_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_html(Path(html_path), network, gateway, devices)


def run_tui(network, gateway: str | None, workers: int, json_path: str, html_path: str) -> int:
    def app(screen):
        curses.curs_set(0)
        screen.keypad(True)
        offset = 0
        devices: list[dict[str, str | None]] = []
        message = "Starting scan…"
        while True:
            screen.erase()
            height, width = screen.getmaxyx()
            screen.addstr(0, 0, "NETMAP  ·  local network inventory", curses.A_BOLD)
            screen.addstr(1, 0, f"Network: {network}    Gateway: {gateway or 'unknown'}")
            screen.addstr(3, 0, message[:max(width - 1, 0)])
            if not devices:
                screen.addstr(5, 0, "No responding devices found yet."[:max(width - 1, 0)])
            else:
                screen.addstr(5, 0, f"{'IP':<18} {'MAC':<20} HOSTNAME", curses.A_UNDERLINE)
                visible = max(height - 9, 1)
                for row, device in enumerate(devices[offset:offset + visible], 6):
                    label = f"{device['ip']:<18} {str(device['mac'] or '—'):<20} {device['hostname'] or '—'}"
                    screen.addstr(row, 0, label[:max(width - 1, 0)])
            footer = "↑/↓ scroll   r rescan   q quit   outputs: JSON + HTML map"
            screen.addstr(height - 1, 0, footer[:max(width - 1, 0)], curses.A_DIM)
            screen.refresh()
            key = screen.getch()
            if key in (ord("q"), ord("Q"), 27):
                break
            if key in (ord("r"), ord("R")):
                screen.addstr(3, 0, "Scanning subnet; please wait…"[:max(width - 1, 0)])
                screen.refresh()
                try:
                    devices = scan(network, gateway, workers)
                    save_report(str(network), gateway, devices, json_path, html_path)
                    message = f"Found {len(devices)} device(s). Saved {json_path} and {html_path}."
                except (OSError, RuntimeError, ValueError) as exc:
                    devices = []
                    message = f"Scan failed: {exc}"
                offset = 0
            elif key in (curses.KEY_DOWN, ord("j")):
                offset = min(offset + 1, max(len(devices) - max(height - 9, 1), 0))
            elif key in (curses.KEY_UP, ord("k")):
                offset = max(offset - 1, 0)
    curses.wrapper(app)
    return 0
