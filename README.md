# netmap

A local network mapper for Linux and macOS. It infers the active IPv4 network, probes hosts on that subnet, reads the system neighbor table, and writes a JSON inventory and self-contained HTML topology map.

## Run

Requires Python 3.10+. Linux needs `ip` and `ping`; macOS uses the built-in `route`, `ifconfig`, `arp`, and `ping` commands.

```sh
python3 -m netmap
```

For a keyboard-driven terminal view, run `python3 -m netmap --tui`. Press `r` to scan or rescan, use the arrow keys (or `j`/`k`) to scroll, and press `q` to quit.

This probes only the subnet attached to the default route. The default is limited to `/24` (256 addresses); larger networks are refused. To target a specific authorized subnet, use `--cidr 192.168.1.0/24`. Use `--max-hosts` to explicitly set a larger limit.

```sh
python3 -m netmap --cidr 192.168.1.0/24 --json devices.json --html map.html
```

The scan uses ICMP echo requests and the local neighbor table. Devices that block ping may not appear. MAC addresses and hostnames are best effort. No data leaves the machine.
# network-map
