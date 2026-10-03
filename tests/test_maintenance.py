"""Offline gates for the weekly maintainer. No SSH, WhatsApp or API calls."""
import copy
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("cluster_maintenance", ROOT / "scripts/cluster-maintenance.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def config(tmp):
    c = json.loads((ROOT / "config/maintenance.example.json").read_text())
    c["enabled"] = True
    c["state_file"] = str(Path(tmp) / "state.json")
    c["lock_file"] = str(Path(tmp) / "lock")
    c["postcheck_timeout_minutes"] = 0
    c["postcheck_poll_seconds"] = 0
    return c


def healthy(c):
    stamp = datetime.now(timezone.utc).isoformat()
    started = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    result = {}
    for name in m.NODES:
        node = c["nodes"][name]
        version_lines = ["This is Eth Docker v26.9.1-dev"]
        version_lines.append({"prysm": "beacon-chain version Prysm/v7.1.8/hash",
                              "lighthouse": "Lighthouse v8.2.2-hash",
                              "lodestar": "  * Version: v1.48.0/hash",
                              "nimbus": "Nimbus beacon node v26.8.0-hash",
                              "remote": "Vero v1.4.1"}[node["cl"]])
        if name in m.SOURCES:
            version_lines.append({"geth": "Geth\nVersion: 1.17.5-stable",
                                  "nethermind": "Nethermind version\nVersion:     1.39.3+hash"}[node["el"]])
        containers = {}
        if name in m.SOURCES:
            containers["eth-docker-consensus-1"] = {"status": "Up", "image": "cl:v1"}
            containers["eth-docker-execution-1"] = {"status": "Up", "image": "el:v1"}
        else:
            containers.update({x: {"status": "Up", "image": "vc:v1"} for x in c["required_vc_containers"]})
        result[name] = {"disk": {"free_gib": 100, "used_pct": 40},
                        "sync": ({"is_syncing": False, "is_optimistic": False, "el_offline": False}
                                 if name in m.SOURCES else {"not_applicable": "remote beacon"}),
                        "containers": containers, "ethd_dirty": "",
                        "ethd_version": "\n".join(version_lines),
                        "reboot_required": False, "boot_id": "current-boot", "pins": {},
                        "apt_upgradable": "Listing..."}
    result["cloudvero"]["attest_logs"] = {
        name: stamp + " Published attestation" for name in
        ("eth-docker-validator-1", "hyperdrive_sw_vc")}
    result["cloudvero"]["vc_started_at"] = {
        name: started for name in ("eth-docker-validator-1", "hyperdrive_sw_vc")}
    return result


class FakeBackend:
    def __init__(self, c):
        self.c = c
        self.inventory = healthy(c)
        self.actions = []
        self.source_build_flags = []
        self.fail_action = False
        self.break_postcheck = False
        self.optimistic_target = False
        self.optimistic_other = False
        self.unexpected_major = False
        self.publish_after_action = True
        self.probes = 0
        self.latest = {
            "eth-docker": {"tag": "v26.9.0"}, "geth": {"tag": "v1.17.7"},
            "nethermind": {"tag": "1.39.4"}, "prysm": {"tag": "v7.2.0"},
            "lighthouse": {"tag": "v8.2.3"}, "lodestar": {"tag": "v1.49.0"},
            "nimbus": {"tag": "v26.9.1"}, "vero": {"tag": "v1.4.1"},
            "hyperdrive": {"tag": "v1.3.0"}}

    def probe(self, node):
        self.probes += 1
        return copy.deepcopy(self.inventory[node["name"]])

    def releases(self):
        return self.latest

    def llm(self, report, releases):
        return {"veto": False, "summary": "reviewed", "reason": ""}

    def action(self, node, kind, source_build=False):
        self.actions.append((node["name"], kind))
        self.source_build_flags.append(source_build)
        if self.fail_action:
            raise m.MaintenanceError("injected action failure")
        if self.break_postcheck:
            self.inventory[node["name"]]["sync"]["is_syncing"] = True
        if self.optimistic_target:
            self.inventory[node["name"]]["sync"]["is_optimistic"] = True
        if self.optimistic_other and node["name"] == "minipcamd":
            self.inventory["minipcamd2"]["sync"]["is_optimistic"] = True
        if self.unexpected_major and node["name"] == "minipcamd" and kind == "clients":
            self.inventory["minipcamd"]["ethd_version"] = self.inventory["minipcamd"]["ethd_version"].replace(
                "Version:     1.39.3+hash", "Version:     2.1.0+hash")
        if self.publish_after_action:
            stamp = datetime.now(timezone.utc).isoformat()
            self.inventory["cloudvero"]["attest_logs"] = {
                name: stamp + " Published attestation" for name in
                ("eth-docker-validator-1", "hyperdrive_sw_vc")}
        return "done"


class FakeBot:
    def __init__(self, fail=False):
        self.fail = fail
        self.alerts = []
        self.conclusions = []

    def alert(self, title, node, detail, approval=False):
        self.alerts.append((title, node, approval))
        if self.fail:
            raise RuntimeError("GestãoBot send failed")
        return {"ok": True, "codigo": "123456" if approval else None}

    def approval(self, code):
        return {"ok": True, "estado": "aprovada"}

    def conclude(self, code, ok, text):
        self.conclusions.append((code, ok))
        return {"ok": True}


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = config(self.tmp.name)
        self.backend = FakeBackend(self.c)
        self.bot = FakeBot()

    def engine(self):
        return m.Engine(self.c, self.backend, self.bot, m.State(Path(self.c["state_file"])), sleeper=lambda _: None)

    def test_missing_health_blocks_all_actions(self):
        self.backend.inventory["minipcamd"]["sync"] = {}
        self.c["nodes"]["minipcamd"]["clients"] = True
        with self.assertRaisesRegex(m.MaintenanceError, "preflight health"):
            self.engine().run()
        self.assertEqual(self.backend.actions, [])

    def test_cloud_without_local_beacon_is_healthy_but_source_false_flags_block(self):
        inv = healthy(self.c)
        self.assertNotIn("eth-docker-consensus-1", inv["cloudvero"]["containers"])
        self.assertEqual(m.health(inv, self.c), [])
        inv["minipcamd"]["sync"]["el_offline"] = True
        self.assertTrue(any("minipcamd: consensus" in x for x in m.health(inv, self.c)))

    def test_both_vcs_require_fresh_publication(self):
        inv = healthy(self.c)
        inv["cloudvero"]["attest_logs"]["hyperdrive_sw_vc"] = "heartbeat with attestation duties"
        self.assertTrue(any("hyperdrive_sw_vc" in x for x in m.health(inv, self.c)))

    def test_attestation_window_covers_duty_gap_but_rejects_stale_logs(self):
        inv = healthy(self.c)
        for minutes, expected in ((12, True), (16, False)):
            stamp = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
            for container in ("eth-docker-validator-1", "hyperdrive_sw_vc"):
                inv["cloudvero"]["attest_logs"][container] = stamp + " Published attestation"
                self.assertEqual(m.published_after(inv["cloudvero"], container), expected)

    def test_quorum_excludes_target(self):
        inv = healthy(self.c)
        for name in m.SOURCES[1:4]:
            inv[name]["sync"]["is_syncing"] = True
        self.assertFalse(m.source_quorum(inv, self.c, "minipcamd"))

    def test_stop_after_first_action_failure(self):
        for name in m.SOURCES[:2]: self.c["nodes"][name]["clients"] = True
        self.backend.fail_action = True
        with self.assertRaisesRegex(m.MaintenanceError, "injected"):
            self.engine().run()
        self.assertEqual(self.backend.actions, [("minipcamd", "clients")])
        self.assertEqual(m.State(Path(self.c["state_file"])).value["status"], "blocked")

    def test_serial_order_and_only_enabled(self):
        self.c["nodes"]["minipcamd"]["clients"] = True
        self.c["nodes"]["minipcamd"]["os"] = True
        self.c["nodes"]["minipcamd2"]["clients"] = True
        result = self.engine().run()
        self.assertEqual(self.backend.actions, [("minipcamd", "clients"),
                                                ("minipcamd", "os"),
                                                ("minipcamd2", "clients")])
        self.assertEqual(result["status"], "partial")

    def test_disabled_does_not_probe_send_or_execute(self):
        self.c["enabled"] = False
        self.c["nodes"]["minipcamd"]["clients"] = True
        self.assertEqual(self.engine().run()["status"], "disabled")
        self.assertEqual(self.backend.probes, 0)
        self.assertEqual(self.backend.actions, [])
        self.assertEqual(self.bot.alerts, [])

    def test_malformed_llm_blocks_before_action(self):
        self.c["nodes"]["minipcamd"]["clients"] = True
        self.backend.llm = lambda *_: m.Backend(self.c).llm({}, {})
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps({"choices": [{"message": {"content": "not json"}}]}).encode()
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fake"}), patch.object(m.urllib.request, "urlopen", return_value=Response()), patch.object(m.time, "sleep"):
            with self.assertRaisesRegex(m.MaintenanceError, "LLM JSON/schema invalid after retry"):
                self.engine().run()
        self.assertEqual(self.backend.actions, [])

    def test_interrupted_state_never_repeats_unknown_action(self):
        state = m.State(Path(self.c["state_file"]))
        state.value = {"status": "running", "phase": "mutating", "current": {"node": "minipcamd", "kind": "clients"}}
        state.save()
        self.c["nodes"]["minipcamd"]["clients"] = True
        with self.assertRaisesRegex(m.MaintenanceError, "manual reconciliation"):
            self.engine().run()
        self.assertEqual(self.backend.actions, [])

    def test_actual_postcheck_failure_blocks_next_node(self):
        for name in m.SOURCES[:2]: self.c["nodes"][name]["clients"] = True
        self.backend.break_postcheck = True
        with self.assertRaisesRegex(m.MaintenanceError, "postcheck timed out"):
            self.engine().run()
        self.assertEqual(self.backend.actions, [("minipcamd", "clients")])

    def test_cloud_postcheck_rejects_pre_action_publications(self):
        self.c["nodes"]["cloudvero"]["clients"] = True
        self.backend.publish_after_action = False
        with self.assertRaisesRegex(m.MaintenanceError, "postcheck timed out"):
            self.engine().run()
        self.assertEqual(self.backend.actions, [("cloudvero", "clients")])

    def test_target_optimistic_never_advances_to_second_node(self):
        self.c["nodes"]["minipcamd"]["clients"] = True
        self.c["nodes"]["minipcamd2"]["clients"] = True
        self.backend.optimistic_target = True
        with self.assertRaisesRegex(m.MaintenanceError, "postcheck timed out"):
            self.engine().run()
        self.assertEqual(self.backend.actions, [("minipcamd", "clients")])

    def test_other_source_optimistic_stops_before_second_action(self):
        self.c["nodes"]["minipcamd"]["clients"] = True
        self.c["nodes"]["minitx"]["clients"] = True
        self.backend.optimistic_other = True
        with self.assertRaisesRegex(m.MaintenanceError, "postcheck other nodes"):
            self.engine().run()
        self.assertEqual(self.backend.actions, [("minipcamd", "clients")])

    def test_cloud_os_excludes_hyperdrive_and_simulates_before_install(self):
        calls = []
        def fake_run(args, **kwargs):
            calls.append(args)
            if args[:3] == ["apt", "list", "--upgradable"]:
                return subprocess.CompletedProcess(args, 0,
                    "Listing...\nhyperdrive/stable 1.3.1 amd64 [upgradable from: 1.3.0]\n"
                    "docker-ce/stable 5:29 amd64 [upgradable from: 5:28]\n", "")
            if "-s" in args:
                return subprocess.CompletedProcess(args, 0, "Inst docker-ce\n", "")
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(subprocess, "run", side_effect=fake_run):
            exec(m.CLOUD_OS_UPGRADE, {})
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[2][-1], "docker-ce")
        self.assertNotIn("hyperdrive", calls[2])

    def test_cloud_os_blocks_transitive_hyperdrive_upgrade(self):
        def fake_run(args, **kwargs):
            if args[:3] == ["apt", "list", "--upgradable"]:
                return subprocess.CompletedProcess(args, 0,
                    "docker-ce/stable 5:29 amd64 [upgradable from: 5:28]\n", "")
            return subprocess.CompletedProcess(args, 0, "Inst hyperdrive\n", "")
        with patch.object(subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(RuntimeError, "would upgrade Hyperdrive"):
                exec(m.CLOUD_OS_UPGRADE, {})

    def test_bot_send_failure_blocks_before_mutation(self):
        self.c["nodes"]["minipcamd"]["clients"] = True
        self.bot.fail = True
        with self.assertRaisesRegex(RuntimeError, "GestãoBot send failed"):
            self.engine().run()
        self.assertEqual(self.backend.actions, [])

    def test_reboot_request_is_persisted_no_reboot_action(self):
        self.c["nodes"]["minipcamd"]["os"] = True
        self.c["nodes"]["minipcamd2"]["clients"] = True
        self.backend.inventory["minipcamd"]["reboot_required"] = True
        result = self.engine().run()
        self.assertEqual(result["pending_reboots"][0]["code"], "123456")
        self.assertEqual(result["pending_reboots"][0]["approval_status"], "aprovada")
        self.assertTrue(any(a[2] for a in self.bot.alerts))
        self.assertEqual(self.backend.actions, [("minipcamd", "os"), ("minipcamd2", "clients")])

    def test_dirty_node_is_skipped_without_stalling_later_nodes(self):
        self.c["nodes"]["minipcamd3"]["clients"] = True
        self.c["nodes"]["minitx"]["clients"] = True
        self.backend.inventory["minipcamd3"]["ethd_dirty"] = "?? .eth/withdrawal-script"
        result = self.engine().run()
        self.assertEqual(self.backend.actions, [("minitx", "clients")])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["skipped"][0]["node"], "minipcamd3")

    def test_source_build_is_explicit_for_dockerfile_source(self):
        self.c["nodes"]["minipcamd"]["clients"] = True
        self.backend.inventory["minipcamd"]["pins"] = {"NM_DOCKERFILE": "Dockerfile.source"}
        self.engine().run()
        self.assertEqual(self.backend.source_build_flags, [True])

    def test_major_client_upgrade_is_skipped_but_os_and_next_node_continue(self):
        self.c["nodes"]["minipcamd"]["clients"] = True
        self.c["nodes"]["minipcamd"]["os"] = True
        self.c["nodes"]["minipcamd2"]["clients"] = True
        self.backend.latest["nethermind"] = {"tag": "2.1.0"}
        result = self.engine().run()
        self.assertEqual(self.backend.actions, [("minipcamd", "os"),
                                                ("minipcamd2", "clients")])
        self.assertEqual(result["inventory"]["minipcamd"]["client_comparison"]["nethermind"],
                         {"installed": "1.39.3", "latest": "2.1.0",
                          "status": "major_review", "fixed_pins": {}})
        self.assertEqual(result["inventory"]["minipcamd"]["effective_plan"],
                         {"clients": False, "os": True})
        self.assertEqual(result["skipped"][0]["kind"], "clients")

    def test_unexpected_post_action_major_blocks_next_node(self):
        self.c["nodes"]["minipcamd"]["clients"] = True
        self.c["nodes"]["minipcamd2"]["clients"] = True
        self.backend.unexpected_major = True
        with self.assertRaisesRegex(m.MaintenanceError, "unexpected/unknown nethermind major"):
            self.engine().run()
        self.assertEqual(self.backend.actions, [("minipcamd", "clients")])
        state = m.State(Path(self.c["state_file"])).value
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["inventory_after"]["minipcamd"]["client_comparison"]["nethermind"]["installed"], "2.1.0")

    def test_all_real_client_version_formats_parse(self):
        inv = healthy(self.c)
        for name in m.NODES:
            comparison = m.client_comparison(inv[name], self.c["nodes"][name], self.backend.latest)
            self.assertTrue(all(v["installed"] for v in comparison.values()), name)

    def test_pending_reboot_skips_only_affected_node_next_cycle(self):
        self.c["nodes"]["minipcamd"]["os"] = True
        self.c["nodes"]["minipcamd2"]["clients"] = True
        state = m.State(Path(self.c["state_file"]))
        state.value = {"status": "complete", "pending_reboots":
                       [{"node": "minipcamd", "code": "123456", "approval_status": "pendente"}]}
        state.save()
        result = self.engine().run()
        self.assertEqual(self.backend.actions, [("minipcamd2", "clients")])
        self.assertEqual(result["pending_reboots"][0]["approval_status"], "aprovada")

    def test_approved_manual_reboot_is_reconciled_from_changed_boot_id(self):
        self.c["nodes"]["minipcamd"]["clients"] = True
        state = m.State(Path(self.c["state_file"]))
        state.value = {"status": "partial", "pending_reboots":
                       [{"node": "minipcamd", "code": "123456", "approval_status": "pendente",
                         "boot_id": "previous-boot"}]}
        state.save()
        result = self.engine().run()
        self.assertEqual(result["pending_reboots"], [])
        self.assertEqual(result["reboot_history"][0]["observed_boot_id"], "current-boot")
        self.assertEqual(self.bot.conclusions, [("123456", True)])
        self.assertEqual(self.backend.actions, [("minipcamd", "clients")])


if __name__ == "__main__":
    unittest.main()
