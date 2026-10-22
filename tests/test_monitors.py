import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from gestaobot_client import BotError, Client


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


health = load("daily_health_test", "daily-health.py")
attest = load("attest_test", "attestation-monitor.py")
notify = load("notify_test", "notify-gestaobot.py")


def healthy():
    result = {n: {"reachable": True, "discos": [("/dev/data", "1.9T", "50%", "/data")],
                  "sync": {"is_syncing": False, "is_optimistic": False, "el_offline": False},
                  "vc": ["eth-docker-execution-1 Up 1 day", "eth-docker-consensus-1 Up 1 day"]}
              for n in health.ESPERADOS}
    result["cloudvero"]["sync"] = None
    result["cloudvero"]["vc"] = [c + " Up 1 day" for c in health.VC_PRECISAM]
    return result


class Monitors(unittest.TestCase):
    def test_missing_probe_is_not_healthy(self):
        data = healthy()
        self.assertEqual(health.analisar(data)[0], 0)
        data["minipcamd"]["reachable"] = False
        self.assertEqual(health.analisar(data)[0], 2)
        del data["minipcamd"]
        self.assertEqual(health.analisar(data)[0], 2)

    def test_large_data_disks_and_sync_are_checked(self):
        data = healthy()
        data["minipcamd"]["discos"][0] = ("/dev/data", "1.9T", "95%", "/data")
        self.assertEqual(health.analisar(data)[0], 2)

    def test_container_down_and_collector_error_are_reported(self):
        data = healthy()
        data["minipcamd"]["vc"] = []
        self.assertEqual(health.analisar(data)[0], 2)
        with patch.object(health, "coletar", side_effect=TimeoutError), patch.object(health, "mandar") as send:
            self.assertEqual(health.main(), 20)
            send.assert_called_once()
        data = healthy()
        data["minipcamd"]["sync"] = None
        self.assertEqual(health.analisar(data)[0], 2)
        data["minipcamd"]["sync"] = {"is_syncing": False}
        self.assertEqual(health.analisar(data)[0], 2)

    def test_send_failure_not_successful_service_exit(self):
        with patch.object(health, "coletar", return_value=healthy()), patch.object(health, "mandar", return_value=False):
            self.assertEqual(health.main(), 20)
        self.assertNotIn("1", (ROOT / "systemd/egkcluster-health.service").read_text().split("SuccessExitStatus=")[1].splitlines()[0].split())

    def test_header_without_probe_status_is_failed(self):
        output = "===== minipcamd =====\n--disk--\n/dev/data 1900000000 900000000 1000000000 48% /data\n--beacon-sync--\n" + json.dumps({"data": healthy()["minipcamd"]["sync"]})
        with patch.object(health.subprocess, "run") as run:
            run.return_value.stdout = output
            data = health.coletar()
        self.assertFalse(data["minipcamd"]["reachable"])
        self.assertEqual(health.analisar(data)[0], 2)

    def test_collector_footer_preserves_success_status(self):
        output = "===== cloudvero =====\n--probe-status--\n0\nCOLLECT-DONE\n"
        with patch.object(health.subprocess, "run") as run:
            run.return_value.stdout = output
            self.assertTrue(health.coletar()["cloudvero"]["reachable"])

    def test_attestation_failed_send_does_not_dedupe(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "alerts.json"
            with patch.object(attest, "ESTADO", state), patch.object(attest, "container_up", return_value=False), patch.object(attest, "mandar", return_value=False):
                self.assertEqual(attest.main(), 20)
            self.assertEqual(json.loads(state.read_text()), {})
            with patch.object(attest, "ESTADO", state), patch.object(attest, "container_up", return_value=False), patch.object(attest, "mandar", return_value=True):
                self.assertEqual(attest.main(), 2)
            self.assertEqual(len(json.loads(state.read_text())), 2)

    def test_optimistic_noise_is_ignored_only_with_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(attest, "ESTADO", Path(directory)/"alerts.json"), patch.object(attest, "container_up", return_value=True), patch.object(attest, "docker_logs", return_value=["Failed to produce attestation data: HeadBlockNotFullyVerified slot=123", "Published attestations slot=123"]), patch.object(attest, "mandar") as send:
                self.assertEqual(attest.main(), 0)
                send.assert_not_called()

    def test_other_slot_publication_does_not_hide_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(attest, "ESTADO", Path(directory)/"alerts.json"), patch.object(attest, "container_up", return_value=True), patch.object(attest, "docker_logs", return_value=["Failed to produce attestation data: HeadBlockNotFullyVerified slot=124", "Published attestations slot=123"]), patch.object(attest, "mandar", return_value=True) as send:
                self.assertEqual(attest.main(), 2)
                self.assertEqual(send.call_count, 2)

    def test_beacon_timeout_names_the_host_and_the_publication(self):
        linha = ("Failed to get a response from beacon node: ConnectionTimeoutError("
                 "'Connection timeout to host http://minipcamd2.velociraptor-scylla.ts.net:5052/eth/v2/beacon/pool/attestations')")
        logs = [linha, linha, "Published attestations slot=10",
                "Using minipcamd.velociraptor-scylla.ts.net as `best` beacon node"]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(attest, "ESTADO", Path(directory)/"alerts.json"), patch.object(attest, "container_up", return_value=True), patch.object(attest, "docker_logs", return_value=logs), patch.object(attest, "mandar", return_value=True) as send:
                self.assertEqual(attest.main(), 2)
        textos = [call.args[1] for call in send.call_args_list]
        self.assertTrue(textos)
        self.assertIn("Beacon sem resposta", [call.args[0] for call in send.call_args_list])
        self.assertTrue(all("erro de atestação" not in texto for texto in textos))
        self.assertIn("minipcamd2 na porta 5052", textos[0])
        self.assertIn("publicou atestação", textos[0])
        self.assertIn("2 vezes", textos[0])
        self.assertIn("beacon escolhido no lugar foi minipcamd", textos[0])

    def test_checkpoint_timeout_with_publication_is_quiet(self):
        logs = [
            "2026-10-22 18:28:49,250 - AttestationService - INFO : Published attestations for slot 15489142, count: 1",
            "2026-10-22 18:30:51,130 - BeaconNode - WARNING: Failed to produce attestation data while waiting for checkpoints: TimeoutError()",
            "2026-10-22 18:34:25,054 - AttestationService - INFO : Published attestations for slot 15489170, count: 1",
        ]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(attest, "ESTADO", Path(directory)/"alerts.json"), patch.object(attest, "container_up", return_value=True), patch.object(attest, "docker_logs", return_value=logs), patch.object(attest, "mandar") as send:
                self.assertEqual(attest.main(), 0)
                send.assert_not_called()

    def test_parallel_half_second_timeouts_with_publication_are_quiet(self):
        futuro = ("future: <Task finished name='Task-1' coro=<BeaconNode.produce_attestation_data() "
                  "done, defined at /vero/providers/beacon_node.py:316> exception=TimeoutError()>")
        logs = [
            "2026-10-22 19:59:14,914 - AttestationService - INFO : Published attestations for slot 15489594, count: 1",
            "2026-10-22 20:00:11,054 - asyncio - ERROR: Task exception was never retrieved",
            futuro, futuro, futuro, futuro, futuro,
            "2026-10-22 20:02:13,480 - AttestationService - INFO : Published attestations for slot 15489609, count: 1",
        ]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(attest, "ESTADO", Path(directory)/"alerts.json"), patch.object(attest, "container_up", return_value=True), patch.object(attest, "docker_logs", return_value=logs), patch.object(attest, "mandar") as send:
                self.assertEqual(attest.main(), 0)
                send.assert_not_called()

    def test_stall_timeouts_name_the_freeze_not_an_unverified_block(self):
        logs = [
            "2026-10-22 19:22:37,020 - AttestationService - INFO : Published attestations for slot 15489411, count: 1",
            "2026-10-22 19:30:07,807 - MultiBeaconNode - WARNING: Failed to produce attestation data: TimeoutError()",
            "2026-10-22 19:30:08,240 - RemoteSigner - ERROR: Failed to get healthcheck response: TimeoutError()",
            "2026-10-22 19:30:08,686 - RemoteSigner - ERROR: Failed to get healthcheck response: ClientResponseError(status=503, message='Service Unavailable', url=URL('http://mainnet-web3signer:9000/healthcheck'))",
            "2026-10-22 19:32:03,722 - event-loop - WARNING: Event loop lag high: 97.41814747301979",
            "2026-10-22 19:34:34,358 - TaskManager - ERROR: RuntimeError('Invalid slot for block proposal: 15489450. Current slot: 15489470')",
            "2026-10-22 19:34:40,513 - MultiBeaconNode - WARNING: Failed to produce attestation data: TimeoutError()",
            "2026-10-22 19:39:48,846 - AttestationService - INFO : Published attestations for slot 15489497, count: 1",
        ]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(attest, "ESTADO", Path(directory)/"alerts.json"), patch.object(attest, "container_up", return_value=True), patch.object(attest, "docker_logs", return_value=logs), patch.object(attest, "mandar", return_value=True) as send:
                self.assertEqual(attest.main(), 2)
        textos = [call.args[1] for call in send.call_args_list]
        self.assertEqual(len(textos), 2)
        self.assertTrue(all("97" in texto for texto in textos))
        self.assertTrue(all("web3signer" in texto for texto in textos))
        self.assertTrue(all("86 slots" in texto for texto in textos))
        self.assertTrue(all("não estava verificado" not in texto for texto in textos))
        self.assertTrue(all("0,5 s" in texto for texto in textos))

    def test_activity_without_publication_is_alerted(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(attest, "ESTADO", Path(directory)/"alerts.json"), patch.object(attest, "container_up", return_value=True), patch.object(attest, "docker_logs", return_value=["Preparing attestation"]), patch.object(attest, "mandar", return_value=True) as send:
                self.assertEqual(attest.main(), 2)
                self.assertEqual(send.call_count, 2)

    def test_bridge_refuses_lead_and_non_local_destinations(self):
        for base in ("http://127.0.0.1:8091", "https://graph.facebook.com", "http://localhost:8101/path"):
            with self.assertRaises(BotError):
                Client(base)
        Client("http://127.0.0.1:8101")

    def test_conclusion_cli_does_not_require_new_alert_fields(self):
        with patch.object(sys, "argv", ["notify", "--concluir", "123456", "--ok", "--texto", "feito"]), patch.object(notify, "Client") as factory:
            factory.return_value.conclude.return_value = {"ok": True}
            self.assertEqual(notify.main(), 0)
            factory.return_value.conclude.assert_called_once_with("123456", True, "feito")


if __name__ == "__main__":
    unittest.main()
