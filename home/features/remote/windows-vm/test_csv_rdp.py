import importlib.util
import io
import os
import subprocess
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

        def spawn(command, pass_fds, **kwargs):
            self.assertNotIn(row["password"], " ".join(command))
            self.assertEqual(command[0], "xfreerdp")
            descriptor = os.dup(pass_fds[0])

            class Process:
                returncode = 0
                stdout = io.StringIO("startup --> CONNECTION_STATE_ACTIVE\n")

                def wait(self):
                    with os.fdopen(descriptor) as source:
                        received.extend(source.read().splitlines())
                    return 0

                def poll(self):
                    return self.returncode

            return Process()

        with patch.object(rdp.subprocess, "Popen", side_effect=spawn), \
             patch.object(rdp.subprocess, "run") as prompt:
            self.assertEqual(rdp.launch(row, ["/f", "/clipboard", "/dvc:rdpecam"]).returncode, 0)
            prompt.assert_not_called()
        self.assertEqual(received, ["/v:10.0.0.1", "/u:User", "/d:DOMAIN", "/f", "/clipboard",
                                    "/dvc:rdpecam", "/timeout:10000", "/log-level:DEBUG",
                                    "/log-filters:com.freerdp.core.rdp:DEBUG,com.freerdp.*:WARN,com.winpr.*:WARN",
                                    "/p:private,pass"])

    def test_wrong_password_then_retry_keeps_worker_alive(self):
        row = dict(name="Test", ip="10.0.0.1", domain_user="DOMAIN\\User", password="")
        password = ' private,quote"pass '
        source = io.StringIO(rdp.json.dumps({"password": "wrong"}) + "\n" +
                             rdp.json.dumps({"password": password}) + "\n")
        results = [subprocess.CompletedProcess([], 0, "ERRCONNECT_LOGON_FAILURE\nAuthentication only, exit status 0"),
                   subprocess.CompletedProcess([], 0, "Authentication only, exit status 1\nERRCONNECT_CONNECT_CANCELLED"),
                   subprocess.CompletedProcess([], 0, "")]
        messages = []
        with patch.object(rdp, "launch", side_effect=results) as client:
            self.assertEqual(rdp.popup_worker(row, [], source, messages.append), 0)
        self.assertIn("rejected", messages[0]["error"])
        self.assertEqual(messages[1:], [{"connected": True}, {"finished": True}])
        self.assertEqual(client.call_args_list[1].kwargs, {"password": password, "auth_only": True})
        self.assertEqual(client.call_args_list[2].kwargs, {"password": password, "auth_only": False})
        self.assertEqual(row["password"], "")

    def test_cancel_or_invalid_password_never_starts_client(self):
        row = dict(name="Test", domain_user="DOMAIN\\User", password="")
        for source in ["", '{"password":""}\n', '{"password":"secret\\nvalue"}\n']:
            with patch.object(rdp, "launch") as client:
                self.assertEqual(rdp.popup_worker(row, [], io.StringIO(source), lambda _: None), 0)
                client.assert_not_called()

    def test_session_failure_reopens_same_popup(self):
        row = dict(name="Test", domain_user="DOMAIN\\User", password="")
        messages = []
        results = [subprocess.CompletedProcess([], 0, "Authentication only, exit status 1"),
                   subprocess.CompletedProcess([], 0, "ERRCONNECT_LOGON_FAILURE")]
        with patch.object(rdp, "launch", side_effect=results):
            rdp.popup_worker(row, [], io.StringIO('{"password":"test"}\n'), messages.append)
        self.assertEqual(messages[0], {"connected": True})
        self.assertIn("rejected", messages[1]["error"])

    def test_auth_only_requires_explicit_success_not_zero_exit(self):
        for code, output, valid in [(0, "", False),
                                    (0, "Authentication only, exit status 0", False),
                                    (0, "ERRCONNECT_LOGON_FAILURE", False),
                                    (0, "Authentication only, exit status 1", True)]:
            result = subprocess.CompletedProcess([], code, output)
            self.assertEqual(rdp.connection_error(result, auth_only=True) is None, valid)

    def test_missing_password_opens_popup_and_saved_failure_is_inline(self):
        args = ["csv", "options", "--launch", "Test"]
        row = dict(name="Test", password="")
        with patch.object(rdp.sys, "argv", ["csv-rdp"] + args), \
             patch.object(rdp, "read_remotes", return_value=[row]), \
             patch("builtins.open", return_value=io.StringIO("[]")), \
             patch.object(rdp, "password_popup", return_value=0) as popup, \
             patch.object(rdp, "launch") as client:
            self.assertEqual(rdp.main(), 0)
            popup.assert_called_once()
            client.assert_not_called()
        row["password"] = "saved"
        with patch.object(rdp.sys, "argv", ["csv-rdp"] + args), \
             patch.object(rdp, "read_remotes", return_value=[row]), \
             patch("builtins.open", return_value=io.StringIO("[]")), \
             patch.object(rdp, "password_popup", return_value=0) as popup, \
             patch.object(rdp, "launch", return_value=subprocess.CompletedProcess([], 0, "ERRCONNECT_LOGON_FAILURE")):
            self.assertEqual(rdp.main(), 0)
            self.assertIn("rejected", popup.call_args.args[1])

    def test_malformed_rows_do_not_expose_secrets(self):
        for record in ['Test,invalid,DOMAIN\\User,secret-value',
                       'Test,10.0.0.1,DOMAIN\\User,"secret\nvalue"']:
            with patch("builtins.open", return_value=io.StringIO("name,ip,domain_user,password\n" + record)):
                with self.assertRaises(ValueError) as error:
                    rdp.read_remotes("unused")
                self.assertNotIn("secret", str(error.exception))

    def test_transient_startup_failure_retries_and_then_succeeds(self):
        failure = subprocess.CompletedProcess([], 0, "self-signed certificate\nERRCONNECT_CONNECT_TRANSPORT_FAILED\nERRCONNECT_CONNECT_CANCELLED")
        success = subprocess.CompletedProcess([], 0, "")
        with patch.object(rdp, "launch", side_effect=[failure, success]) as client, \
             patch.object(rdp.time, "sleep") as delay:
            self.assertIs(rdp.connect_with_retry({}, []), success)
        self.assertEqual(client.call_count, 2)
        delay.assert_called_once_with(0.75)

    def test_retries_are_bounded(self):
        failure = subprocess.CompletedProcess([], 1, "ERRCONNECT_CONNECT_FAILED")
        with patch.object(rdp, "launch", return_value=failure) as client, \
             patch.object(rdp.time, "sleep") as delay:
            self.assertIs(rdp.connect_with_retry({}, []), failure)
        self.assertEqual(client.call_count, 3)
        self.assertEqual([call.args[0] for call in delay.call_args_list], [0.75, 1.5])

    def test_silent_zero_exit_before_activation_is_retried(self):
        failure = subprocess.CompletedProcess([], 0, "")
        failure.session_started = False
        success = subprocess.CompletedProcess([], 0, "")
        success.session_started = True
        with patch.object(rdp, "launch", side_effect=[failure, success]) as client, \
             patch.object(rdp.time, "sleep"):
            self.assertIs(rdp.connect_with_retry({}, []), success)
            self.assertEqual(client.call_count, 2)

    def test_password_certificate_cancellation_and_active_session_do_not_retry(self):
        results = [subprocess.CompletedProcess([], 0, "ERRCONNECT_LOGON_FAILURE\nERRCONNECT_CONNECT_TRANSPORT_FAILED"),
                   subprocess.CompletedProcess([], 1, "ERRCONNECT_CERT_CONNECT_ERROR\nERRCONNECT_TLS_CONNECT_FAILED"),
                   subprocess.CompletedProcess([], 1, "ERRCONNECT_CONNECT_CANCELLED")]
        active = subprocess.CompletedProcess([], 1, "ERRCONNECT_CONNECT_TRANSPORT_FAILED")
        active.session_started = True
        results.append(active)
        for result in results:
            with patch.object(rdp, "launch", return_value=result) as client, \
                 patch.object(rdp.time, "sleep") as delay:
                self.assertIs(rdp.connect_with_retry({}, []), result)
                client.assert_called_once()
                delay.assert_not_called()


if __name__ == "__main__":
    unittest.main()
