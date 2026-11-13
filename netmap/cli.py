"""Command line interface for the local network mapper."""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import ipaddress
import json
import math
import platform
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def run(*args: str) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=4)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Could not run {args[0]}: {exc}") from exc
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"{args[0]} exited with status {result.returncode}")
    return result.stdout


def linux_default_network() -> tuple[ipaddress.IPv4Network, str | None]:
    routes = run("ip", "-4", "route", "show", "default").splitlines()
    if not routes:
        raise RuntimeError("No default IPv4 route found. Connect to a network or provide --cidr.")
    fields = routes[0].split()
    gateway = fields[fields.index("via") + 1] if "via" in fields else None
    interface = fields[fields.index("dev") + 1] if "dev" in fields else None
    if not interface:
        raise RuntimeError("Could not determine the network interface for the default route.")
    lines = run("ip", "-4", "-o", "addr", "show", "dev", interface).splitlines()
    for line in lines:
        fields = line.split()
        if "inet" in fields:
            address = fields[fields.index("inet") + 1]
            return ipaddress.ip_interface(address).network, gateway
    raise RuntimeError(f"No IPv4 address found on interface {interface}.")


def macos_default_network() -> tuple[ipaddress.IPv4Network, str | None]:
    gateway = None
    interface = None
    try:
        for line in run("netstat", "-rn", "-f", "inet").splitlines():
            fields = line.split()
            if len(fields) >= 4 and fields[0] == "default":
                gateway, interface = fields[1], fields[-1]
                break
    except RuntimeError:
        pass
    if not interface:
        route = run("route", "-n", "get", "default")
        fields = dict(line.strip().split(":", 1) for line in route.splitlines() if ":" in line)
        gateway = fields.get("gateway", "").strip() or None
        interface = fields.get("interface", "").strip()
    if not interface:
        raise RuntimeError("Could not determine the interface for the default route.")
    for line in run("ifconfig", interface).splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[0] == "inet":
            address = fields[1]
            mask = fields[3]
            try:
                netmask = str(ipaddress.IPv4Address(int(mask, 16))) if mask.startswith("0x") else mask
                return ipaddress.ip_network(f"{address}/{netmask}", strict=False), gateway
            except ipaddress.AddressValueError as exc:
                raise RuntimeError(f"Invalid IPv4 netmask on {interface}: {mask}") from exc
    raise RuntimeError(f"No IPv4 address found on interface {interface}.")


def default_network() -> tuple[ipaddress.IPv4Network, str | None]:
    system = platform.system()
    if system == "Linux":
        return linux_default_network()
    if system == "Darwin":
        return macos_default_network()
    raise RuntimeError(f"Unsupported operating system: {system}")


def neighbor_table() -> dict[str, str]:
    result: dict[str, str] = {}
    if platform.system() == "Linux":
        for line in run("ip", "-4", "neigh", "show").splitlines():
            fields = line.split()
            if "lladdr" in fields:
                result[fields[0]] = fields[fields.index("lladdr") + 1]
    elif platform.system() == "Darwin":
        for line in run("arp", "-an").splitlines():
            fields = line.split()
            if len(fields) >= 4 and fields[1].startswith("(") and fields[3] != "(incomplete)":
                result[fields[1][1:-1]] = fields[3]
    return result


def probe(address: str) -> bool:
    wait_flag = "1000" if platform.system() == "Darwin" else "1"
    try:
        result = subprocess.run(
            ["ping", "-n", "-c", "1", "-W", wait_flag, address],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=2,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def scan(network: ipaddress.IPv4Network, gateway: str | None, workers: int) -> list[dict[str, str | None]]:
    known = neighbor_table()
    targets = list(network.hosts())
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        alive = [str(ip) for ip, ok in zip(targets, pool.map(probe, map(str, targets))) if ok]
    addresses = sorted(set(alive) | (set(known) & {str(ip) for ip in targets}), key=ipaddress.ip_address)
    devices = []
    for address in addresses:
        try:
            hostname = socket.gethostbyaddr(address)[0]
        except (socket.herror, OSError):
            hostname = None
        devices.append({"ip": address, "mac": known.get(address), "hostname": hostname,
                        "role": "gateway" if address == gateway else "device"})
    return devices


def write_html(path: Path, network: str, gateway: str | None, devices: list[dict[str, str | None]]) -> None:
    rows = "\n".join(
        f'<tr><td>{html.escape(str(d["ip"]))}</td><td>{html.escape(str(d["hostname"] or "—"))}</td>'
        f'<td>{html.escape(str(d["mac"] or "—"))}</td><td>{html.escape(str(d["role"]))}</td></tr>'
        for d in devices
    )
    nodes = []
    count = max(len(devices), 1)
    for index, device in enumerate(devices):
        x = 500 + 390 * math.cos(2 * math.pi * index / count)
        y = 190 + 130 * math.sin(2 * math.pi * index / count)
        nodes.append(
            f'<line x1="500" y1="190" x2="{x:.1f}" y2="{y:.1f}" />'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" />'
            f'<text x="{x:.1f}" y="{y + 27:.1f}">{html.escape(str(device["ip"]))}</text>'
        )
    topology = "\n".join(nodes)
    page = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Network map</title><style>body{{font:16px system-ui;max-width:1000px;margin:3rem auto;padding:0 1rem;background:#101827;color:#e5eefb}}h1{{color:#25e96b}}table{{width:100%;border-collapse:collapse}}th,td{{padding:.7rem;text-align:left;border-bottom:1px solid #344258}}th{{color:#9fb1c8}}svg{{width:100%;background:#121e30;border-radius:1rem}}line{{stroke:#25e96b;stroke-opacity:.55;stroke-width:2}}circle{{fill:#25e96b;stroke:#101827;stroke-width:3}}text{{fill:#e5eefb;font:14px system-ui;text-anchor:middle}}.router{{fill:#172a42;stroke:#25e96b;stroke-width:3}}</style>
<h1>Wi-Fi network map</h1><p>Network: {html.escape(network)} · Gateway: {html.escape(gateway or "unknown")}</p>
<svg viewBox="0 0 1000 380" role="img" aria-label="Network topology map">{topology}<circle class="router" cx="500" cy="190" r="34"/><text x="500" y="187">Router</text><text x="500" y="207">{html.escape(gateway or "unknown")}</text></svg>
<table><thead><tr><th>IP</th><th>Hostname</th><th>MAC</th><th>Role</th></tr></thead><tbody>{rows}</tbody></table>
<p>Generated {datetime.now(timezone.utc).isoformat()}</p>"""
    path.write_text(page, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Map devices on an authorized local IPv4 network.")
    parser.add_argument("--cidr", help="IPv4 subnet to scan; defaults to the default-route subnet")
    parser.add_argument("--max-hosts", type=int, default=256, help="Maximum addresses to probe (default: 256)")
    parser.add_argument("--workers", type=int, default=32, help="Concurrent ping probes (default: 32)")
    parser.add_argument("--json", dest="json_path", default="network-map.json", help="JSON output path")
    parser.add_argument("--html", dest="html_path", default="network-map.html", help="HTML output path")
    parser.add_argument("--tui", action="store_true", help="open the interactive terminal interface")
    args = parser.parse_args(argv)
    system = platform.system()
    required = {"Linux": ("ip", "ping"), "Darwin": ("netstat", "route", "ifconfig", "arp", "ping")}.get(system)
    if required is None:
        parser.error(f"Unsupported operating system: {system}. Supported systems: Linux and macOS.")
    missing = [cmd for cmd in required if shutil.which(cmd) is None]
    if missing:
        parser.error("Missing required command(s): " + ", ".join(missing))
    if args.max_hosts < 1 or args.workers < 1:
        parser.error("--max-hosts and --workers must be positive")
    try:
        if args.cidr:
            network = ipaddress.ip_network(args.cidr, strict=False)
            if not isinstance(network, ipaddress.IPv4Network):
                raise ValueError("Only IPv4 subnets are supported")
            gateway = None
        else:
            network, gateway = default_network()
        if network.num_addresses > args.max_hosts:
            raise ValueError(f"{network} has {network.num_addresses} addresses, over --max-hosts={args.max_hosts}")
        if args.tui:
            from .tui import run_tui
            return run_tui(network, gateway, min(args.workers, args.max_hosts), args.json_path, args.html_path)
        devices = scan(network, gateway, min(args.workers, args.max_hosts))
        report = {"network": str(network), "gateway": gateway, "scanned_at": datetime.now(timezone.utc).isoformat(), "devices": devices}
        Path(args.json_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        write_html(Path(args.html_path), str(network), gateway, devices)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"netmap: {exc}", file=sys.stderr)
        return 2
    print(f"Found {len(devices)} device(s) on {network}; wrote {args.json_path} and {args.html_path}")
    return 0
