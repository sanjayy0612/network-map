import json
import ipaddress
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from netmap import cli


class HtmlOutputTests(unittest.TestCase):
    def test_map_contains_topology_and_escapes_device_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.html"
            cli.write_html(path, "192.168.1.0/24", "192.168.1.1", [
                {"ip": "192.168.1.4", "mac": None, "hostname": "<script>", "role": "device"}
            ])
            page = path.read_text()
        self.assertIn("Network topology map", page)
        self.assertIn("<line", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>", page)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.platform = patch.object(cli.platform, "system", return_value="Linux")
        self.which = patch.object(cli.shutil, "which", return_value="/usr/bin/found")
        self.platform.start()
        self.which.start()
        self.addCleanup(self.platform.stop)
        self.addCleanup(self.which.stop)

    def test_oversized_network_is_rejected_before_scan(self):
        with patch.object(cli, "scan") as scan:
            result = cli.main(["--cidr", "192.168.0.0/16"])
        self.assertEqual(result, 2)
        scan.assert_not_called()

    def test_cli_writes_json_and_html(self):
        devices = [{"ip": "192.168.1.2", "mac": "aa:bb:cc:dd:ee:ff", "hostname": None, "role": "device"}]
        with tempfile.TemporaryDirectory() as directory:
            json_path = str(Path(directory) / "devices.json")
            html_path = str(Path(directory) / "map.html")
            with patch.object(cli, "scan", return_value=devices):
                result = cli.main(["--cidr", "192.168.1.0/24", "--json", json_path, "--html", html_path])
            report = json.loads(Path(json_path).read_text())
            page = Path(html_path).read_text()
        self.assertEqual(result, 0)
        self.assertEqual(report["network"], "192.168.1.0/24")
        self.assertEqual(report["devices"], devices)
        self.assertIn("192.168.1.2", page)

    def test_default_network_uses_default_route_interface_address(self):
        outputs = [
            "default via 192.168.1.1 dev wlan0 proto dhcp\n",
            "2: wlan0 inet 192.168.1.20/24 brd 192.168.1.255 scope global wlan0\n",
        ]
        with patch.object(cli, "run", side_effect=outputs) as run:
            network, gateway = cli.default_network()
        self.assertEqual(str(network), "192.168.1.0/24")
        self.assertEqual(gateway, "192.168.1.1")
        self.assertEqual(run.call_count, 2)

    def test_macos_default_network_parses_route_and_netmask(self):
        outputs = [
            "Destination Gateway Flags Netif\ndefault 192.168.1.1 UGScg en0\n",
            "en0: flags=8863<UP>\n\tinet 192.168.1.20 netmask 0xffffff00 broadcast 192.168.1.255\n",
        ]
        with patch.object(cli.platform, "system", return_value="Darwin"), patch.object(cli, "run", side_effect=outputs):
            network, gateway = cli.default_network()
        self.assertEqual(str(network), "192.168.1.0/24")
        self.assertEqual(gateway, "192.168.1.1")

    def test_tui_option_enters_tui_without_scanning_inline(self):
        with patch.object(cli, "default_network", return_value=(ipaddress.ip_network("192.168.1.0/24"), "192.168.1.1")), \
             patch("netmap.tui.run_tui", return_value=0) as tui, patch.object(cli, "scan") as scan:
            result = cli.main(["--tui"])
        self.assertEqual(result, 0)
        tui.assert_called_once()
        scan.assert_not_called()

    def test_macos_neighbor_parser_reads_arp_cache(self):
        output = "? (192.168.1.2) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]\n"
        with patch.object(cli.platform, "system", return_value="Darwin"), patch.object(cli, "run", return_value=output):
            neighbors = cli.neighbor_table()
        self.assertEqual(neighbors["192.168.1.2"], "aa:bb:cc:dd:ee:ff")

    def test_scan_merges_ping_replies_with_neighbor_cache(self):
        with patch.object(cli, "neighbor_table", return_value={"192.168.1.2": "aa:bb:cc:dd:ee:ff"}), \
             patch.object(cli, "probe", side_effect=lambda ip: ip == "192.168.1.1"), \
             patch.object(cli.socket, "gethostbyaddr", side_effect=OSError):
            devices = cli.scan(ipaddress.ip_network("192.168.1.0/30"), "192.168.1.1", 2)
        self.assertEqual([item["ip"] for item in devices], ["192.168.1.1", "192.168.1.2"])
        self.assertEqual(devices[0]["role"], "gateway")
        self.assertEqual(devices[1]["mac"], "aa:bb:cc:dd:ee:ff")


if __name__ == "__main__":
    unittest.main()
