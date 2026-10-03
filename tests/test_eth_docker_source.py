import copy
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from eth_docker_source import migrate_env,env_values,validate_compose
import eth_docker_source as source


class SourceTests(unittest.TestCase):
    def test_settings_and_pins_preserved_when_defaults_change(self):
        old='ENV_VERSION=68\nNETWORK=mainnet\nPG_DOCKER_TAG=18-trixie\nJWT_SECRET=private-test\nCL_NODE="https://custom.invalid"\nFEE_RECIPIENT=0x123\n'
        new='ENV_VERSION=72\nNETWORK=hoodi\nPG_DOCKER_TAG=19\nJWT_SECRET=\nCL_NODE=default\nFEE_RECIPIENT=\nNEW_PORT=9010\n'
        result,report=migrate_env(old,new)
        before,after=env_values(old),env_values(result)
        self.assertEqual({k:v for k,v in after.items() if k in before and k!='ENV_VERSION'},
                         {k:v for k,v in before.items() if k!='ENV_VERSION'})
        self.assertEqual(after['NEW_PORT'],'9010')
        self.assertNotIn('private-test',str(report))

    def test_legacy_always_builder_policy_survives_schema72(self):
        text,_=migrate_env('ENV_VERSION=68\nEPBS_BUILD_FACTOR="00100"\n','ENV_VERSION=72\nEPBS_BUILD_FACTOR=\n')
        self.assertEqual(env_values(text)['EPBS_BUILD_FACTOR'],'always')

    def test_current_factor100_keeps_profit_maximization(self):
        text,_=migrate_env('ENV_VERSION=72\nEPBS_BUILD_FACTOR=100\n','ENV_VERSION=72\nEPBS_BUILD_FACTOR=\n')
        self.assertEqual(env_values(text)['EPBS_BUILD_FACTOR'],'100')

    def test_unknown_schema_and_downgrade_refused(self):
        for old,new in [(68,73),(73,72),(50,72)]:
            with self.assertRaises(ValueError):migrate_env('ENV_VERSION='+str(old)+'\n','ENV_VERSION='+str(new)+'\n')

    def test_explicit_flat_configuration_needs_review(self):
        with self.assertRaises(ValueError):migrate_env('ENV_VERSION=68\nNETHERMIND_FLATDB=flatintrie\n','ENV_VERSION=72\n')

    def test_tools_profiles_are_not_activated(self):
        with self.assertRaises(ValueError):migrate_env('ENV_VERSION=68\nCOMPOSE_PROFILES=tools\n','ENV_VERSION=72\n')

    def test_volume_or_postgres_major_change_refused(self):
        old={'services':{'postgres':{'image':'postgres:18','volumes':[{'source':'slashing','target':'/data'}]}}}
        for key,value in [('image','postgres:19'),('volumes',[{'source':'new','target':'/data'}])]:
            new=copy.deepcopy(old);new['services']['postgres'][key]=value
            with self.assertRaises(ValueError):validate_compose(old,new,['postgres'])

    def test_protected_signing_settings_refused(self):
        old={'services':{'validator':{'environment':{'CL_NODE':'old','FEE_RECIPIENT':'same'}}}}
        new=copy.deepcopy(old);new['services']['validator']['environment']['CL_NODE']='new'
        with self.assertRaises(ValueError):validate_compose(old,new,['validator'])


class SourceGitIntegrationTests(unittest.TestCase):
    """Real Git merges, with only Docker inspection replaced by a fixed inventory."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.upstream, self.live = base / 'upstream', base / 'eth-docker'
        self.upstream.mkdir()
        self.git(self.upstream, 'init', '-q')
        self.git(self.upstream, 'config', 'user.name', 'test')
        self.git(self.upstream, 'config', 'user.email', 'test@localhost')
        self.original = ('ENV_VERSION=68\nNETWORK=mainnet\n'
                         'COMPOSE_FILE=${CORE_FILES}${CUSTOM_FILES:+:${CUSTOM_FILES}}\n'
                         'CORE_FILES=core.yml\nCUSTOM_FILES=\nPG_DOCKER_TAG=18-trixie\n')
        (self.upstream / 'default.env').write_text(self.original)
        (self.upstream / '.gitignore').write_text('.env\n.env.*\n')
        (self.upstream / 'core.yml').write_text('services: {}\n')
        (self.upstream / 'base.txt').write_text('original\n')
        self.git(self.upstream, 'add', '.')
        self.git(self.upstream, 'commit', '-qm', 'base')
        subprocess.run(['git', 'clone', '-q', str(self.upstream), str(self.live)], check=True)
        self.git(self.live, 'config', 'user.name', 'test')
        self.git(self.live, 'config', 'user.email', 'test@localhost')
        (self.live / '.env').write_text(self.original)
        (self.live / 'local-overlay.txt').write_text('operator patch\n')
        self.git(self.live, 'add', 'local-overlay.txt')
        self.git(self.live, 'commit', '-qm', 'local overlay')
        (self.upstream / 'default.env').write_text(self.original.replace('ENV_VERSION=68', 'ENV_VERSION=72') + 'NEW_DEFAULT=1\n')
        (self.upstream / 'base.txt').write_text('upstream update\n')
        self.git(self.upstream, 'add', '.')
        self.git(self.upstream, 'commit', '-qm', 'official update')
        self.revision = self.git(self.upstream, 'rev-parse', 'HEAD')
        self.old_head = self.git(self.live, 'rev-parse', 'HEAD')
        self.real_run = subprocess.run

    @staticmethod
    def git(directory, *args):
        return subprocess.check_output(['git', *args], cwd=directory, text=True, stderr=subprocess.DEVNULL).strip()

    def mocked_run(self, args, **kwargs):
        if args[0] != 'docker':
            return self.real_run(args, **kwargs)
        if args[1] == 'compose':
            data = {'services': {name: {'image': name + ':existing', 'volumes': [], 'environment': {}}
                                 for name in ('validator', 'web3signer', 'postgres')}}
            stdout = json.dumps(data)
        elif args[1] == 'ps':
            stdout = 'validator\nweb3signer\npostgres\n'
        elif args[1] == 'inspect':
            stdout = args[-1]
        else:
            raise AssertionError('unexpected Docker mutation')
        return subprocess.CompletedProcess(args, 0, stdout, '')

    def prepare(self, apply=True):
        with patch.object(source, 'UPSTREAM', str(self.upstream)), patch.object(source.subprocess, 'run', side_effect=self.mocked_run):
            return source.prepare(str(self.live), self.revision, apply=apply)

    def test_merge_preserves_local_history_settings_and_storage_containers(self):
        result = self.prepare()
        for ancestor in (self.old_head, self.revision):
            self.git(self.live, 'merge-base', '--is-ancestor', ancestor, 'HEAD')
        self.assertEqual((self.live / 'local-overlay.txt').read_text(), 'operator patch\n')
        self.assertEqual((self.live / 'base.txt').read_text(), 'upstream update\n')
        self.assertEqual(env_values((self.live / '.env').read_text())['PG_DOCKER_TAG'], '18-trixie')
        self.assertEqual(stat.S_IMODE((self.live / '.env').stat().st_mode), 0o600)
        self.assertEqual(self.git(self.live, 'status', '--porcelain'), '')
        self.assertEqual(result['apply_services'], ['validator'])
        self.assertTrue(result['applied'])
        self.assertEqual((Path(result['backup']) / 'env-before').read_text(), self.original)

    def test_preview_does_not_change_live_code_or_environment(self):
        result = self.prepare(apply=False)
        self.assertFalse(result['applied'])
        self.assertEqual(self.git(self.live, 'rev-parse', 'HEAD'), self.old_head)
        self.assertEqual((self.live / '.env').read_text(), self.original)

    def test_conflict_stays_in_preview_and_live_tree_is_unchanged(self):
        (self.live / 'base.txt').write_text('operator override\n')
        self.git(self.live, 'add', 'base.txt')
        self.git(self.live, 'commit', '-qm', 'conflicting patch')
        before = self.git(self.live, 'rev-parse', 'HEAD')
        with self.assertRaisesRegex(RuntimeError, 'git failed'):
            self.prepare()
        self.assertEqual(self.git(self.live, 'rev-parse', 'HEAD'), before)
        self.assertEqual((self.live / '.env').read_text(), self.original)
        self.assertEqual(self.git(self.live, 'status', '--porcelain'), '')


if __name__=='__main__':unittest.main()
