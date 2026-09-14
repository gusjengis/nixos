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
