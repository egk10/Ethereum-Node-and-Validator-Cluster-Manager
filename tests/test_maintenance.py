"""Offline gates for the weekly maintainer. No SSH, WhatsApp or API calls."""
import copy
import importlib.util
import io
import json
import os
import tempfile
import unittest
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
    result = {}
    for name in m.NODES:
        containers = {}
        if name in m.SOURCES:
            containers["eth-docker-consensus-1"] = {"status": "Up", "image": "cl:v1"}
            containers["eth-docker-execution-1"] = {"status": "Up", "image": "el:v1"}
        else:
            containers.update({x: {"status": "Up", "image": "vc:v1"} for x in c["required_vc_containers"]})
        result[name] = {"disk": {"free_gib": 100, "used_pct": 40},
                        "sync": ({"is_syncing": False, "is_optimistic": False, "el_offline": False}
                                 if name in m.SOURCES else {"not_applicable": "remote beacon"}),
                        "containers": containers, "ethd_dirty": "", "ethd_version": "v1",
                        "reboot_required": False, "boot_id": "current-boot", "pins": {},
                        "apt_upgradable": "Listing..."}
    result["cloudvero"]["attest_logs"] = {"eth-docker-validator-1": "Published attestation"}
    return result


class FakeBackend:
    def __init__(self, c):
        self.c = c
        self.inventory = healthy(c)
        self.actions = []
        self.source_build_flags = []
        self.fail_action = False
        self.break_postcheck = False
        self.probes = 0

    def probe(self, node):
        self.probes += 1
        return copy.deepcopy(self.inventory[node["name"]])

    def releases(self):
        return {k: {"tag": "v2"} for k in m.REPOS}

    def llm(self, report, releases):
        return {"veto": False, "summary": "reviewed", "reason": ""}

    def action(self, node, kind, source_build=False):
        self.actions.append((node["name"], kind))
        self.source_build_flags.append(source_build)
        if self.fail_action:
            raise m.MaintenanceError("injected action failure")
        if self.break_postcheck:
            self.inventory[node["name"]]["sync"]["is_syncing"] = True
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
