"""Reboot approval and exactly-once gates; never invokes a live reboot."""
import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from test_maintenance import m, config, FakeBackend, FakeBot, healthy, ROOT
spec = importlib.util.spec_from_file_location('approved_reboot',ROOT/'scripts/approved-reboot.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class ApprovedRebootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = config(self.tmp.name)
        self.st = m.State(Path(self.tmp.name)/'state.json')
        self.st.value = {'status':'partial','pending_reboots':[{'node':'cloudvero','code':'123456','approval_status':'pendente'}]}
        self.rp = m.State(Path(self.tmp.name)/'reboot.json')
        self.rp.value = {'phase':'awaiting-approval','code':'123456','boot_id_before':'before',
                         'services':[],'settings_hashes':{},'containers_before':{}}
        self.backend = FakeBackend(self.c)
        self.bot = FakeBot()
        self.engine = m.Engine(self.c,self.backend,self.bot,self.st,lambda _:None)

    def test_expired_approval_never_issues_reboot(self):
        self.bot.approval = lambda _: {'estado':'expirada'}
        with patch.object(r,'boot_id',return_value='before'), patch.object(r,'shell') as shell:
            result = r.execute(self.c,self.st,self.rp,self.engine)
        self.assertEqual(result['status'],'approval-not-granted')
        self.assertEqual(self.st.value['pending_reboots'][0]['approval_status'],'expirada')
        shell.assert_not_called()

    def test_approval_with_optimistic_source_never_issues_reboot(self):
        self.backend.inventory['minitx']['sync']['is_optimistic'] = True
        with patch.object(r,'boot_id',return_value='before'),patch.object(r,'service_issues',return_value=[]), \
             patch.object(r,'shell') as shell:
            with self.assertRaisesRegex(r.m.MaintenanceError,'Approved reboot preflight'):
                r.execute(self.c,self.st,self.rp,self.engine)
        shell.assert_not_called()

    def test_approved_reboot_journal_saved_before_schedule(self):
        calls=[]
        def shell(args):
            calls.append(args)
            if 'systemd-run' in args:
                self.assertEqual(m.State(self.rp.path).value['phase'],'reboot-scheduled')
                self.assertEqual(m.State(self.st.path).value['status'],'running')
                return 'scheduled'
            return 'enabled'
        with patch.object(r,'boot_id',return_value='before'),patch.object(r,'service_issues',return_value=[]), \
             patch.object(r.h,'settings_hashes',return_value={}),patch.object(r.h,'inspect_all',return_value={}), \
             patch.object(r,'shell',side_effect=shell):
            result=r.execute(self.c,self.st,self.rp,self.engine)
        self.assertEqual(result['status'],'reboot-scheduled')
        self.assertEqual(sum('systemd-run' in call for call in calls),1)
        with patch.object(r,'boot_id',return_value='before'),patch.object(r,'shell') as shell:
            with self.assertRaisesRegex(r.m.MaintenanceError,'not awaiting approval'):
                r.execute(self.c,self.st,self.rp,self.engine)
        shell.assert_not_called()

    def test_recovery_on_same_boot_does_not_repeat_reboot(self):
        self.rp.value['phase']='reboot-scheduled'
        with patch.object(r,'boot_id',return_value='before'),patch.object(r,'shell') as shell:
            with self.assertRaisesRegex(r.m.MaintenanceError,'changed boot ID'):
                r.recover(self.c,self.st,self.rp,self.engine)
        shell.assert_not_called()

    def test_stopped_operator_must_stay_stopped_and_images_preserved(self):
        old={'id':'same','image_id':'sha256:old','status':'exited','restart':{'Name':'no'},'started_at':'before'}
        new={'Id':'same','Image':'sha256:old','State':{'Status':'running','StartedAt':'after'},
             'HostConfig':{'RestartPolicy':{'Name':'no'}}}
        with self.assertRaisesRegex(r.m.MaintenanceError,'running/stopped state'):
            r.assert_boot_containers({'hyperdrive_sw_operator':old},{'hyperdrive_sw_operator':new})
        new['State']['Status']='exited'
        r.assert_boot_containers({'hyperdrive_sw_operator':old},{'hyperdrive_sw_operator':new})
        new['Image']='sha256:other'
        with self.assertRaisesRegex(r.m.MaintenanceError,'image_id changed'):
            r.assert_boot_containers({'hyperdrive_sw_operator':old},{'hyperdrive_sw_operator':new})

    def expired_session_request(self):
        self.rp.value.update(phase='approval-not-granted',approval_status='expirada',releases=self.backend.latest)
        self.st.value['pending_reboots'][0]['approval_status']='expirada'
        self.backend.inventory['cloudvero']['reboot_required']=True

    def test_explicit_session_authorization_preserves_expired_bot_record(self):
        self.expired_session_request()
        self.bot.approval=Mock(side_effect=AssertionError('Session authorization must not poll or manufacture bot approval'))
        live={}
        for name in ('hyperdrive_sw_operator','eth-lido-validator-1','eth-lido-web3signer-1',r.h.VC):
            live[name]={'Id':name,'Image':'sha256:old','State':{'Status':'exited' if name!=r.h.VC else 'running',
                          'StartedAt':'before'},'HostConfig':{'RestartPolicy':{'Name':'no' if name!=r.h.VC else 'unless-stopped'}},
                        'Mounts':[],'Config':{'Entrypoint':['sh'],'Cmd':['validator'],'User':'root'}}
        with patch.object(r,'boot_id',return_value='before'),patch.object(r,'services_running',return_value=[]), \
             patch.object(r,'service_issues',return_value=[]),patch.object(r.h,'inspect_all',return_value=live), \
             patch.object(r.h,'settings_hashes',return_value={}),patch.object(r,'shell',return_value='enabled') as shell:
            result=r.execute_session(self.c,self.st,self.rp,self.engine,'Rebota o cloudvero')
        self.assertEqual(result['status'],'reboot-scheduled')
        self.assertIsNone(self.rp.value['code'])
        self.assertEqual(self.rp.value['authorization']['channel'],'user-session')
        self.assertNotIn('approved_at',self.rp.value)
        self.assertEqual(self.st.value['pending_reboots'],[])
        self.assertEqual(self.st.value['superseded_reboot_requests'][0]['approval_status'],'expirada')
        self.assertEqual(self.st.value['active_session_reboot']['authorization'],self.rp.value['authorization'])
        self.bot.approval.assert_not_called()
        self.assertEqual(sum('systemd-run' in call.args[0] for call in shell.call_args_list),1)

    def test_session_reboot_still_blocks_on_any_optimistic_source(self):
        self.expired_session_request()
        self.backend.inventory['minipcamd2']['sync']['is_optimistic']=True
        with patch.object(r,'boot_id',return_value='before'),patch.object(r,'services_running',return_value=[]), \
             patch.object(r,'service_issues',return_value=[]),patch.object(r,'shell') as shell:
            with self.assertRaisesRegex(r.m.MaintenanceError,'Session reboot preflight'):
                r.execute_session(self.c,self.st,self.rp,self.engine,'Rebota o cloudvero')
        shell.assert_not_called()
        self.assertFalse(self.rp.path.exists())

    def test_session_instruction_is_specific_and_recovery_requires_matching_record(self):
        with self.assertRaisesRegex(r.m.MaintenanceError,'exact recorded user instruction'):
            r.execute_session(self.c,self.st,self.rp,self.engine,'run automatic maintenance')
        self.rp.value.update(phase='reboot-scheduled',authorization={'channel':'user-session','instruction':'Rebota o cloudvero'})
        with patch.object(r,'boot_id',return_value='after'),patch.object(r,'shell') as shell:
            with self.assertRaisesRegex(r.m.MaintenanceError,'recorded explicit session authorization'):
                r.recover(self.c,self.st,self.rp,self.engine)
        shell.assert_not_called()


if __name__ == '__main__':
    unittest.main()
