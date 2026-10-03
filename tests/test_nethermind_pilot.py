"""Pilot behavior: one target, exact release, durable failure, global recovery."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from test_maintenance import FakeBackend, FakeBot, config

spec = importlib.util.spec_from_file_location(
    "nethermind_pilot", Path(__file__).resolve().parents[1] / "scripts/nethermind-pilot.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class Backend(FakeBackend):
    def __init__(self, c):
        super().__init__(c)
        for node in self.inventory.values():
            for container in node['containers'].values():
                container['image_id'] = 'sha256:' + '1' * 64
            node['sync']['head_slot'] = '100'
        self.audit = {'old_image_id':'sha256:' + '1' * 64, 'old_container_id':'old',
                      'env_sha256':'same-env', 'entrypoint_sha256':'same-script',
                      'data_volume':'same-volume', 'database_path':'same-path',
                      'database_backend':'patricia'}
        self.candidate_version = '2.1.0'
        self.candidate = 'sha256:' + '2' * 64
        self.changed = []
        self.fail_build = False
        self.break_before_apply = False

    def _command(self, node, script, timeout):
        output = ''
        if p.AUDIT in script:
            output = json.dumps(self.audit)
        elif p.m.CANDIDATE_PROBE in script:
            output = json.dumps({'nethermind':{'image_id':self.candidate,
                                 'version_output':'Version: ' + self.candidate_version}})
        elif 'cmd build' in script:
            if self.fail_build:
                raise p.m.MaintenanceError('build failed before live apply')
            if self.break_before_apply:
                self.inventory['minipcamd2']['sync']['is_optimistic'] = True
        elif 'cmd up' in script:
            self.changed.append(node['name'])
            self.inventory[node['name']]['ethd_version'] = self.inventory[node['name']]['ethd_version'].replace(
                'Version:     1.39.3+hash', 'Version:     2.1.0+hash')
            self.inventory[node['name']]['containers']['eth-docker-execution-1']['image_id'] = self.candidate
            self.inventory[node['name']]['sync']['head_slot'] = '120'
            if self.optimistic_target:
                self.inventory[node['name']]['sync']['is_optimistic'] = True
            if self.optimistic_other:
                self.inventory['minipcamd2']['sync']['is_optimistic'] = True
            self.pending_publication = self.publish_after_action
        return subprocess.CompletedProcess([], 0, output, '')


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = config(self.tmp.name)
        self.backend = Backend(self.c)
        self.state = p.m.State(Path(self.c['state_file']))
        self.report = p.m.State(Path(self.tmp.name) / 'pilot.json')
        self.bot = FakeBot()
        self.pilot = p.Pilot(self.c, self.backend, self.bot, self.state, self.report, sleeper=lambda _:None)

    def test_complete_changes_only_selected_execution_and_releases_state(self):
        result = self.pilot.run('minipcamd')
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(self.backend.changed, ['minipcamd'])
        self.assertEqual(self.state.value['status'], 'pilot_complete')
        self.assertTrue(all(self.report.value['fresh_attestations'].values()))

    def test_other_node_optimistic_before_pilot_prevents_any_change(self):
        self.backend.inventory['minitx']['sync']['is_optimistic'] = True
        with self.assertRaises(p.m.MaintenanceError): self.pilot.run('minipcamd')
        self.assertEqual(self.backend.changed, [])
        self.assertEqual(self.bot.alerts, [])

    def test_health_changes_during_build_prevent_apply(self):
        self.backend.break_before_apply = True
        with self.assertRaises(p.m.MaintenanceError): self.pilot.run('minipcamd')
        self.assertEqual(self.backend.changed, [])
        self.assertEqual(self.state.value['status'], 'blocked')

    def test_future_release_is_not_covered_by_pilot_authorization(self):
        self.backend.candidate_version = '2.2.0'
        with self.assertRaises(p.m.MaintenanceError): self.pilot.run('minipcamd')
        self.assertEqual(self.backend.changed, [])

    def test_target_optimistic_after_apply_cannot_complete(self):
        self.backend.optimistic_target = True
        with self.assertRaises(p.m.MaintenanceError): self.pilot.run('minipcamd')
        self.assertEqual(self.state.value['status'], 'blocked')

    def test_other_node_optimistic_after_apply_cannot_complete(self):
        self.backend.optimistic_other = True
        with self.assertRaises(p.m.MaintenanceError): self.pilot.run('minipcamd')
        self.assertEqual(self.state.value['status'], 'blocked')

    def test_old_attestations_cannot_release_pilot(self):
        self.backend.publish_after_action = False
        with self.assertRaises(p.m.MaintenanceError): self.pilot.run('minipcamd')
        self.assertEqual(self.state.value['status'], 'blocked')

    def test_unknown_previous_mutation_is_not_repeated(self):
        self.state.value['status'] = 'blocked'
        with self.assertRaises(p.m.MaintenanceError): self.pilot.run('minipcamd')
        self.assertEqual(self.backend.changed, [])

    def test_completed_pilot_does_not_repeat_upgrade(self):
        self.pilot.run('minipcamd')
        with self.assertRaises(p.m.MaintenanceError): self.pilot.run('minipcamd')
        self.assertEqual(self.backend.changed, ['minipcamd'])


if __name__ == '__main__':
    unittest.main()
