import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("system_controls", Path(__file__).with_name("system-controls.py"))
controls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)


class NmcliParsingTests(unittest.TestCase):
    def test_decodes_escaped_colons_and_backslashes(self):
        self.assertEqual(
            controls.split_nmcli(r"*:Cafe\: downstairs:82:WPA2\\Enterprise"),
            ["*", "Cafe: downstairs", "82", r"WPA2\Enterprise"],
        )

    def test_deduplicates_ssids_preferring_connected_then_signal(self):
        networks = controls.parse_wifi_networks(
            " :Cafe\\: downstairs:91:WPA2\n"
            "*:Cafe\\: downstairs:55:WPA2\n"
            " :Other:72:\n"
            " :Other:40:\n"
        )

        self.assertEqual([item["ssid"] for item in networks], ["Cafe: downstairs", "Other"])
        self.assertTrue(networks[0]["connected"])
        self.assertEqual(networks[0]["signal"], 55)
        self.assertEqual(networks[1]["signal"], 72)


class ActiveNetworkTests(unittest.TestCase):
    def test_primary_connection_selects_wired_or_wireless(self):
        # The primary connection wins even when another device has carrier,
        # another Wi-Fi connection is associated, or Tailscale is also active.
        for connection_type, expected in (
            ("802-3-ethernet", "ethernet"),
            ("802-11-wireless", "wifi"),
            ("tun", None),
            ("bridge", None),
        ):
            with self.subTest(connection_type=connection_type), patch.object(
                controls, "run", side_effect=[
                    '{"type":"o","data":"/org/freedesktop/NetworkManager/ActiveConnection/7"}',
                    controls.json.dumps({"type": "s", "data": connection_type}),
                ],
            ) as run:
                self.assertEqual(controls.active_network_type(), expected)
                self.assertEqual(run.call_args.args[0][-3:], [
                    "/org/freedesktop/NetworkManager/ActiveConnection/7",
                    "org.freedesktop.NetworkManager.Connection.Active", "Type",
                ])

    def test_no_primary_connection_is_disconnected(self):
        with patch.object(controls, "run", return_value='{"type":"o","data":"/"}') as run:
            self.assertIsNone(controls.active_network_type())
        self.assertEqual(run.call_count, 1)

    def test_wired_state_works_with_wifi_off(self):
        with patch.object(controls, "active_network_type", return_value="ethernet"), patch.object(
            controls, "run", return_value="disabled\n",
        ):
            state = controls.wifi_state()
        self.assertEqual(state["activeType"], "ethernet")
        self.assertFalse(state["enabled"])
        self.assertIsNone(state["connected"])

    def test_primary_lookup_failure_preserves_wifi_controls(self):
        with patch.object(controls, "active_network_type", side_effect=RuntimeError("lookup failed")), patch.object(
            controls, "run", side_effect=["enabled\n", "*:Office:82:WPA2\n"],
        ):
            state = controls.wifi_state()
        self.assertIsNone(state["activeType"])
        self.assertEqual(state["connected"], {"ssid": "Office", "signal": 82})
        self.assertEqual(state["error"], "lookup failed")


class SafetyTests(unittest.TestCase):
    def test_rejects_non_mac_bluetooth_address_without_subprocess(self):
        with patch.object(controls, "run") as run:
            with self.assertRaisesRegex(ValueError, "invalid Bluetooth address"):
                controls.perform("bluetooth-connect", ["AA:BB:CC:DD:EE:FF;reboot"])
        run.assert_not_called()

    def test_wifi_connect_passes_password_over_stdin(self):
        with patch.object(controls, "run") as run:
            controls.perform("wifi-connect", ["Cafe; reboot", "$(secret)"])

        self.assertEqual(
            run.call_args.args[0],
            ["nmcli", "--ask", "device", "wifi", "connect", "Cafe; reboot"],
        )
        self.assertEqual(run.call_args.kwargs["input_text"], "$(secret)\n")

    def test_pair_trusts_device_after_pairing(self):
        with patch.object(controls, "run") as run:
            controls.perform("bluetooth-pair", ["AA:BB:CC:DD:EE:FF"])

        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ["bluetoothctl", "pair", "AA:BB:CC:DD:EE:FF"],
                ["bluetoothctl", "trust", "AA:BB:CC:DD:EE:FF"],
            ],
        )


class BrightnessTests(unittest.TestCase):
    def test_parses_machine_readable_state(self):
        self.assertEqual(
            controls.parse_brightness("intel_backlight,backlight,2400,12000,20%\n"),
            {"available": True, "percent": 20, "name": "intel_backlight"},
        )

    def test_parses_installed_brightnessctl_field_order(self):
        self.assertEqual(
            controls.parse_brightness("intel_backlight,backlight,1515,100%,1515\n"),
            {"available": True, "percent": 100, "name": "intel_backlight"},
        )

    def test_unavailable_hardware_returns_stable_state(self):
        with patch.object(controls, "run", side_effect=RuntimeError("No devices found")):
            self.assertEqual(controls.brightness_state(), {"available": False, "percent": 0})

    def test_set_validates_range_before_safe_argv_call(self):
        with patch.object(controls, "run") as run:
            controls.perform("brightness-set", ["73"])
            self.assertEqual(run.call_args.args[0], ["brightnessctl", "set", "73%"])

            for value in ("-1", "101", "2.5", "50;reboot"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    controls.perform("brightness-set", [value])

        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
