"""Compare saved network inventories without probing the network."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path


def load_inventory(path: str) -> tuple[str, dict[str, str]]:
    if not Path(path).is_file():
        raise ValueError(f"{path}: report file not found. Run a scan with --json {path} first.")
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc.msg}") from exc
    if not isinstance(report, dict) or not isinstance(report.get("network"), str) or not isinstance(report.get("devices"), list):
        raise ValueError(f"{path}: expected a netmap report with network and devices")
    try:
        network = ipaddress.IPv4Network(report["network"], strict=False)
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError) as exc:
        raise ValueError(f"{path}: invalid IPv4 network") from exc
    addresses: dict[str, str] = {}
    seen: set[str] = set()
    for device in report["devices"]:
        if not isinstance(device, dict) or not isinstance(device.get("ip"), str):
            raise ValueError(f"{path}: device is missing an IP address")
        try:
            address = ipaddress.IPv4Address(device["ip"])
        except ipaddress.AddressValueError as exc:
            raise ValueError(f"{path}: invalid device IP address") from exc
        if address not in network or str(address) in seen:
            raise ValueError(f"{path}: duplicate or out-of-network device IP: {address}")
        seen.add(str(address))
        mac = device.get("mac")
        if mac is not None and not isinstance(mac, str):
            raise ValueError(f"{path}: invalid MAC address for {address}")
        if mac:
            addresses[str(address)] = mac.strip().lower()
    return str(network), addresses


def changed_macs(old_path: str, new_path: str) -> list[tuple[str, str, str]]:
    old_network, old = load_inventory(old_path)
    new_network, new = load_inventory(new_path)
    if old_network != new_network:
        raise ValueError(f"Cannot compare different networks: {old_network} and {new_network}")
    return [
        (ip, old[ip], new[ip])
        for ip in sorted(old.keys() & new.keys(), key=ipaddress.IPv4Address)
        if old[ip] != new[ip]
    ]
