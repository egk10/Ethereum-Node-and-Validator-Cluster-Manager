"""Reboot approval and exactly-once gates; never invokes a live reboot."""
import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == '__main__':
    unittest.main()
