"""Safety gates for the validator-only Hyperdrive recipe, without live Docker."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_maintenance import m, config, FakeBackend, FakeBot, healthy
import hyperdrive_vc as h


class WeeklyHyperdriveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = config(self.tmp.name)
        self.c['nodes']['cloudvero']['hyperdrive'] = True
        self.backend = FakeBackend(self.c)
        self.bot = FakeBot()

    def run_weekly(self):
        return m.Engine(self.c,self.backend,self.bot,m.State(Path(self.c['state_file'])),lambda _:None).run()

    def test_only_hyperdrive_vc_selected_and_version_image_confirmed(self):
        result = self.run_weekly()
        self.assertEqual(self.backend.actions,[('cloudvero','hyperdrive')])
        self.assertEqual(result['inventory_after']['cloudvero']['hyperdrive_comparison']['lodestar']['status'],'current')
        self.assertFalse(any('Hyperdrive' in x for x in result['inventory_after']['cloudvero']['gaps']))

    def test_current_hyperdrive_does_not_restart_vc(self):
        self.backend.inventory['cloudvero']['hyperdrive_vc_version'] = '  * Version: v1.49.0/hash'
        self.run_weekly()
        self.assertEqual(self.backend.actions,[])

    def test_hyperdrive_cli_or_daemon_upgrade_requires_review(self):
        self.backend.latest['hyperdrive']['tag'] = 'v1.4.0'
        result = self.run_weekly()
        self.assertEqual(self.backend.actions,[])
        self.assertEqual(result['skipped'][0]['kind'],'hyperdrive')

    def test_any_optimistic_source_blocks_hyperdrive(self):
        self.backend.inventory['minipcamd3']['sync']['is_optimistic'] = True
        with self.assertRaisesRegex(m.MaintenanceError,'preflight health'):
            self.run_weekly()
        self.assertEqual(self.backend.actions,[])

    def test_false_gap_removed_only_when_all_observed_versions_current(self):
        inv = healthy(self.c)
        for n in m.NODES:
            self.c['nodes'][n]['source'] = True
            node = self.c['nodes'][n]
            for client in m.client_comparison(inv[n],node,self.backend.latest):
                current = m.client_comparison(inv[n],node,self.backend.latest)[client]['installed']
                inv[n]['ethd_version'] = inv[n]['ethd_version'].replace(current,self.backend.latest[client]['tag'].lstrip('v'))
        inv['cloudvero']['hyperdrive_vc_version'] = '  * Version: v1.49.0/hash'
        self.backend.latest['eth-docker']['source'] = {'supported':True}
        inv['minitx']['pins'] = {'GETH_DOCKER_TAG':'v1.17.7'}
        report = m.inventory_report(inv,self.backend.latest,self.c)
        self.assertEqual({n:r['gaps'] for n,r in report.items() if r['gaps']},{})
        inv['cloudvero']['hyperdrive_vc_version'] = {'error':'not running'}
        self.assertTrue(m.inventory_report(inv,self.backend.latest,self.c)['cloudvero']['gaps'])


class HyperdriveRecipeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.live = {'Id':'old-vc','Image':'sha256:old','Name':'/hyperdrive_sw_vc',
                     'State':{'Status':'running','StartedAt':'yesterday'},
                     'HostConfig':{'RestartPolicy':{'Name':'unless-stopped'}},
                     'Mounts':[{'Type':'bind','Source':str(self.root),'Destination':'/validators','RW':True},
                               {'Type':'bind','Source':'/scripts','Destination':'/usr/share/hyperdrive/scripts','RW':False}],
                     'Config':{'Image':h.IMAGE,'Entrypoint':['sh'],'Cmd':['validator.sh'],'User':'root',
                               'Env':['TEST_SECRET=private'],
                               'Labels':{'com.docker.compose.project':'hyperdrive','com.docker.compose.service':'sw_vc',
                                         'com.docker.compose.project.working_dir':str(h.ROOT),
                                         'com.docker.compose.project.config_files':','.join(map(str,h.FILES))}}}
        self.render = {'services':{'sw_vc':{'image':h.IMAGE,'entrypoint':['sh'],
            'command':['validator.sh'],'user':'root','environment':{'TEST_SECRET':'private'},
            'volumes':[{'type':'bind','source':str(self.root),'target':'/validators'},
                       {'type':'bind','source':'/scripts','target':'/usr/share/hyperdrive/scripts','read_only':True}]}}}
        self.prior = {'installed':'1.48.0','latest':'v1.49.0','fixed_pins':{}}

    def test_existing_signing_context_is_accepted(self):
        self.assertEqual(h.validate_render(self.render,self.live)['image'],h.IMAGE)

    def test_changed_slashing_bind_blocks_before_applying(self):
        self.render['services']['sw_vc']['volumes'][0]['source'] = '/new-data'
        with self.assertRaisesRegex(RuntimeError,'signing/slashing mounts'):
            h.validate_render(self.render,self.live)

    def test_changed_validator_command_or_environment_blocks_without_secret_output(self):
        self.render['services']['sw_vc']['environment']['TEST_SECRET'] = 'changed-private'
        with self.assertRaisesRegex(RuntimeError,'environment differs') as exc:
            h.validate_render(self.render,self.live)
        self.assertNotIn('private',str(exc.exception))

    def test_major_candidate_and_unexpected_mutable_tag_block(self):
        for output in ('  * Version: v2.0.0/hash','  * Version: v1.48.0/hash'):
            with self.assertRaisesRegex(RuntimeError,'candidate requires review'):
                h.check_candidate(output,self.prior)
        self.assertEqual(h.check_candidate('  * Version: v1.49.0/hash',self.prior),'1.49.0')

    def test_non_target_operator_start_is_rejected(self):
        before = {h.VC:self.live,'hyperdrive_sw_operator':copy.deepcopy(self.live)}
        before['hyperdrive_sw_operator']['State']['Status'] = 'exited'
        after = copy.deepcopy(before)
        after['hyperdrive_sw_operator']['State']['Status'] = 'running'
        with self.assertRaisesRegex(RuntimeError,'Non-target container changed'):
            h.assert_preserved(before,after)

    def test_health_recheck_after_pull_blocks_live_compose_up(self):
        calls = []
        def docker(*args,**kwargs):
            calls.append(args)
            if args[:2] == ('image','inspect'):
                return 'null' if '{{json .Config.Volumes}}' in args else 'sha256:' + 'a'*64
            if args[0] == 'run':
                return '  * Version: v1.49.0/hash'
            return ''
        def health(_):
            raise RuntimeError('source became optimistic')
        with patch.object(h,'inspect_all',return_value={h.VC:self.live}), \
             patch.object(h,'settings_hashes',return_value={}), \
             patch.object(h,'version_output',return_value='  * Version: v1.48.0/hash'), \
             patch.object(h,'docker',side_effect=docker), \
             patch.object(h,'command',return_value=json.dumps(self.render)) as compose_command, \
             patch.object(h,'FILES',()), patch.object(h,'ROOT',self.root):
            (self.root/'user-settings.yml').write_text('test configuration')
            # The actual labels are checked against this fixture's deployment.
            self.live['Config']['Labels']['com.docker.compose.project.working_dir'] = str(self.root)
            self.live['Config']['Labels']['com.docker.compose.project.config_files'] = ''
            with self.assertRaisesRegex(RuntimeError,'source became optimistic'):
                h.update(self.prior,health,self.root)
            self.assertFalse(any('up' in c.args[0] for c in compose_command.call_args_list))
        isolated = next(x for x in calls if x[0] == 'run')
        self.assertIn('--read-only',isolated)
        self.assertIn('none',isolated)
        self.assertNotIn('-v',isolated)


if __name__ == '__main__':
    unittest.main()
