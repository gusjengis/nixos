import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("csv_rdp", Path(__file__).with_name("csv-rdp.py"))
rdp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rdp)


class CsvRdpTests(unittest.TestCase):
    def test_csv_quoting_and_runtime_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "remotes.csv"
            path.write_text('name,ip,domain_user,password\nTest,10.0.0.1,DOMAIN\\User,"comma,quote""pass"\n')
            row = rdp.read_remotes(path)[0]
            self.assertEqual(row["password"], 'comma,quote"pass')
            path.write_text("name,ip,domain_user,password\nOther,10.0.0.2,DOMAIN\\Other,\n")
            self.assertEqual([row["name"] for row in rdp.read_remotes(path)], ["Other"])

    def test_fd_transport_and_existing_rdp_options(self):
        row = dict(name="Test", ip="10.0.0.1", domain_user="DOMAIN\\User", password="private,pass")
        received = []

        def spawn(command, pass_fds):
            self.assertNotIn(row["password"], " ".join(command))
            self.assertEqual(command[0], "xfreerdp")
            descriptor = os.dup(pass_fds[0])

            class Process:
                def wait(self):
                    with os.fdopen(descriptor) as source:
                        received.extend(source.read().splitlines())
                    return 0

            return Process()

        with patch.object(rdp.subprocess, "Popen", side_effect=spawn):
            self.assertEqual(rdp.launch(row, ["/f", "/clipboard", "/dvc:rdpecam"]), 0)
        self.assertEqual(received, ["/v:10.0.0.1", "/u:User", "/d:DOMAIN", "/f", "/clipboard",
                                    "/dvc:rdpecam", "/p:private,pass"])

    def test_blank_password_never_starts_client(self):
        with patch.object(rdp.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(ValueError, "Password missing"):
                rdp.launch(dict(name="Test", password=""), [])
            spawn.assert_not_called()

    def test_malformed_rows_do_not_expose_secrets(self):
        for record in ['Test,invalid,DOMAIN\\User,secret-value',
                       'Test,10.0.0.1,DOMAIN\\User,"secret\nvalue"']:
            with patch("builtins.open", return_value=io.StringIO("name,ip,domain_user,password\n" + record)):
                with self.assertRaises(ValueError) as error:
                    rdp.read_remotes("unused")
                self.assertNotIn("secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
