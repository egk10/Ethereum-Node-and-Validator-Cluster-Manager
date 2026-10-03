#!/usr/bin/env python3
"""Cloudvero-only reboot after GestãoBot approval, with durable boot recovery."""
import argparse
import fcntl
import importlib.util
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from gestaobot_client import Client
import hyperdrive_vc as h

spec = importlib.util.spec_from_file_location('maintenance',Path(__file__).with_name('cluster-maintenance.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
REPORT = 'cloudvero-approved-reboot-20261003.json'
CORE = ('docker.service','tailscaled.service','nginx.service','haproxy.service',
        'integra-leadbot.service','integra-botinterno.service','integra-painel.service',
        'integra-web.service','integra-ig.service')
TIMERS = ('egkcluster-health.timer','egkcluster-maintenance.timer','egkcluster-attestations.timer')


def shell(args):
    return subprocess.check_output(args,text=True,timeout=60,stdin=subprocess.DEVNULL).strip()


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def services_running():
    rows = shell(['systemctl','list-units','--type=service','--state=running','--no-legend','--plain'])
    return sorted(set(CORE) | {line.split()[0] for line in rows.splitlines()
                              if line.split()[0].startswith('integra-')})


def service_issues(services):
    issues = []
    for unit in (*services,*TIMERS):
        try:
            if shell(['systemctl','is-active',unit]) != 'active':
                issues.append(unit + ': inactive')
        except subprocess.CalledProcessError:
            issues.append(unit + ': inactive')
    for unit in (*CORE,*TIMERS):
        try:
            if shell(['systemctl','is-enabled',unit]) != 'enabled':
                issues.append(unit + ': not enabled')
        except subprocess.CalledProcessError:
            issues.append(unit + ': not enabled')
    for port in (8091,8101):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=8) as response:
                if response.status != 200:
                    issues.append(f'HTTP health {port}: not 200')
        except Exception:
            issues.append(f'HTTP health {port}: unavailable')
    return issues


def assert_boot_containers(before,after):
    if set(before) != set(after):
        raise m.MaintenanceError('Ethereum container inventory changed across reboot')
    for name, old in before.items():
        new = h.identity(after[name])
        for field in ('id','image_id','restart'):
            if new[field] != old[field]:
                raise m.MaintenanceError(f'{name}: {field} changed across reboot')
        if (new['status']=='running') != (old['status']=='running'):
            raise m.MaintenanceError(name + ': running/stopped state changed across reboot')


def pending(st,code):
    rows = [x for x in st.value.get('pending_reboots',[]) if x.get('code') == code and x.get('node') == 'cloudvero']
    if len(rows) != 1:
        raise m.MaintenanceError('Approved reboot record missing or ambiguous')
    return rows[0]


def prepare(c,st,rp,engine):
    if rp.value or st.value.get('status') in ('running','blocked'):
        raise m.MaintenanceError('Existing reboot/maintenance state requires reconciliation')
    inv = engine.probe_all()
    issues = m.health(inv,c) + service_issues(services_running())
    if issues or inv['cloudvero'].get('reboot_required') is not True:
        raise m.MaintenanceError('Reboot preparation: ' + '; '.join(issues or ['reboot not required']))
    releases = engine.backend.releases()
    if m.hyperdrive_blockers(inv['cloudvero'],releases):
        raise m.MaintenanceError('Hyperdrive migration remains unresolved')
    if m.hyperdrive_comparison(inv['cloudvero'],releases)['lodestar']['status'] != 'current':
        raise m.MaintenanceError('Finish Hyperdrive VC update before reboot')
    live = h.inspect_all()
    operator = live['hyperdrive_sw_operator']
    if operator['State']['Status'] == 'running':
        raise m.MaintenanceError('Expected intentionally stopped Hyperdrive operator')
    # Persist its existing stopped state even if Docker's restart manager runs at boot.
    old_policy = operator['HostConfig']['RestartPolicy']
    h.docker('update','--restart=no','hyperdrive_sw_operator')
    live = h.inspect_all()
    services = services_running()
    rp.value = {'status':'prepared','phase':'prepared','prepared_at':m.now(),
                'boot_id_before':boot_id(),'kernel_before':shell(['uname','-r']),
                'services':services,'settings_hashes':h.settings_hashes(),
                'containers_before':{n:h.identity(v) for n,v in live.items()},
                'signing_context_sha256':h.digest(h.signing_context(live[h.VC])),
                'operator_restart_before':old_policy,'inventory_before':inv,'releases':releases}
    rp.save()
    response = engine.alert('Reboot cloudvero: kernel atualizado','cloudvero',
        'Reiniciar somente cloudvero para ativar o kernel já instalado. Vero, Hyperdrive VC e bots '
        'ficam indisponíveis durante a reinicialização. Os cinco pares EL/CL permanecem ativos. '
        'Operator/eth-lido ficam parados; configuração, dados de assinatura e threshold 2 preservados. '
        'Após /aprovar CÓDIGO, serviço independente verifica saúde, executa uma vez e valida a recuperação.',approval=True)
    code = response['codigo']
    rp.value.update(status='awaiting-approval',phase='awaiting-approval',code=code,approval=response)
    rp.save()
    old = [x for x in st.value.get('pending_reboots',[]) if x['node']=='cloudvero']
    st.value.setdefault('superseded_reboot_requests',[]).extend(old)
    st.value['pending_reboots'] = [x for x in st.value.get('pending_reboots',[]) if x['node']!='cloudvero']
    st.value['pending_reboots'].append({'node':'cloudvero','code':code,'approval_status':'pendente',
        'requested_at':m.now(),'boot_id':rp.value['boot_id_before'],'report':str(rp.path)})
    st.save()
    return {'status':'awaiting-approval','code':code,'expira_em':response.get('expira_em'),'report':str(rp.path)}


def execute(c,st,rp,engine):
    if rp.value.get('phase') != 'awaiting-approval' or boot_id() != rp.value['boot_id_before']:
        raise m.MaintenanceError('Reboot is not awaiting approval on its original boot')
    item = pending(st,rp.value['code'])
    deadline = time.monotonic()+16*60
    while True:
        result = engine.bot.approval(rp.value['code'])
        status = result['estado']
        item.update(approval_status=status,checked_at=m.now())
        st.save()
        if status == 'aprovada':
            break
        if status != 'pendente' or time.monotonic() >= deadline:
            rp.value.update(status='approval-not-granted',phase='approval-not-granted',approval_status=status)
            rp.save()
            return {'status':'approval-not-granted','approval_status':status}
        time.sleep(10)
    inv = engine.probe_all()
    issues = m.health(inv,c) + service_issues(rp.value['services'])
    if issues or not m.source_quorum(inv,c,'cloudvero'):
        raise m.MaintenanceError('Approved reboot preflight: ' + '; '.join(issues))
    if h.settings_hashes() != rp.value['settings_hashes']:
        raise m.MaintenanceError('Hyperdrive configuration changed since approval request')
    current = h.inspect_all()
    for name,expected in rp.value['containers_before'].items():
        if name not in current or h.identity(current[name]) != expected:
            raise m.MaintenanceError('Ethereum container changed since approval request: ' + name)
    if engine.bot.approval(rp.value['code'])['estado'] != 'aprovada':
        raise m.MaintenanceError('GestãoBot approval no longer valid')
    if shell(['systemctl','is-enabled','egkcluster-reboot-recovery.service']) != 'enabled':
        raise m.MaintenanceError('Persistent reboot recovery service is not enabled')
    engine.alert('Reboot cloudvero: iniciando','cloudvero',
                 'Aprovação '+rp.value['code']+' confirmada. Cinco sources saudáveis; recovery persistente habilitado. '
                 'Vero/Hyperdrive e GestãoBot retornarão após a reinicialização.')
    rp.value.update(status='running',phase='reboot-scheduled',approved_at=m.now(),scheduled_at=m.now())
    rp.save()
    st.value.update(status='running',phase='cloudvero-reboot/reboot-scheduled',
                    current={'node':'cloudvero','kind':'reboot','code':rp.value['code'],'report':str(rp.path)})
    st.save()
    shell(['sudo','-n','systemd-run','--unit=egkcluster-approved-cloudvero-reboot','--on-active=20s',
           '/usr/bin/systemctl','reboot'])
    return {'status':'reboot-scheduled','code':rp.value['code']}


def recover(c,st,rp,engine):
    if rp.value.get('phase') not in ('reboot-scheduled','recovering'):
        return {'status':'no-recovery-needed'}
    if boot_id() == rp.value['boot_id_before']:
        raise m.MaintenanceError('Recovery requires a changed boot ID; never repeats a reboot')
    if pending(st,rp.value['code']).get('approval_status') != 'aprovada':
        raise m.MaintenanceError('Recovery requires recorded GestãoBot approval')
    rp.value.update(phase='recovering',boot_id_after=boot_id(),recovery_started_at=m.now())
    rp.save()
    deadline = time.monotonic()+30*60
    while True:
        try:
            inv = engine.probe_all()
            issues = m.health(inv,c) + service_issues(rp.value['services'])
            if Path('/var/run/reboot-required').exists():
                issues.append('reboot-required remains present')
            live = h.inspect_all()
            assert_boot_containers(rp.value['containers_before'],live)
            if h.digest(h.signing_context(live[h.VC])) != rp.value['signing_context_sha256']:
                raise m.MaintenanceError('Hyperdrive signing context changed across reboot')
            if h.settings_hashes() != rp.value['settings_hashes']:
                raise m.MaintenanceError('Hyperdrive configuration changed across reboot')
            if not issues:
                break
        except Exception as exc:
            issues = [str(exc)]
        rp.value.update(last_health_issues=issues,last_check_at=m.now())
        rp.save()
        if time.monotonic() >= deadline:
            raise m.MaintenanceError('Reboot recovery timeout: '+'; '.join(issues))
        time.sleep(30)
    # No pre-boot publication can pass m.health: it checks each VC's current StartedAt.
    outcome = engine.bot.conclude(rp.value['code'],True,
        'Cloudvero reiniciado; kernel '+shell(['uname','-r'])+'. Boot ID mudou e reboot-required ausente. '
        'Cinco sources synced/não otimistas/EL online; ambos VCs publicaram após iniciar. '
        'GestãoBot/Leadbot HTTP 200 e serviços/timers ativos. Operator/eth-lido seguem parados.')
    report = m.inventory_report(inv,rp.value['releases'],c)
    item = pending(st,rp.value['code'])
    st.value.setdefault('reboot_history',[]).append({**item,'observed_boot_id':boot_id(),
                                                   'reconciled_at':m.now(),'report':str(rp.path)})
    st.value['pending_reboots'].remove(item)
    st.value.update(inventory_after=report,gaps_summary={n:r['gaps'] for n,r in report.items() if r['gaps']},
                    phase='done',finished_at=m.now())
    st.value.update(status='partial' if st.value['pending_reboots'] or st.value['gaps_summary'] else 'complete')
    st.value.pop('current',None)
    st.value.pop('error',None)
    st.save()
    rp.value.update(status='complete',phase='complete',finished_at=m.now(),kernel_after=shell(['uname','-r']),
                    inventory_after=inv,health_issues=[],conclusion=outcome)
    rp.save()
    shell(['sudo','-n','systemctl','disable','egkcluster-reboot-recovery.service'])
    return {'status':'complete','code':rp.value['code'],'kernel':rp.value['kernel_after'],'report':str(rp.path)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config',type=Path,required=True)
    group = ap.add_mutually_exclusive_group(required=True)
    for arg in ('prepare','execute','recover'):
        group.add_argument('--'+arg,action='store_true')
    args = ap.parse_args()
    c = m.checked_config(args.config)
    if not c['enabled']:
        raise m.MaintenanceError('Explicit enabled configuration required')
    with Path(c['lock_file']).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        st,rp = m.State(Path(c['state_file'])),m.State(Path(c['state_file']).parent/REPORT)
        engine = m.Engine(c,m.Backend(c),Client(),st)
        result = prepare(c,st,rp,engine) if args.prepare else execute(c,st,rp,engine) if args.execute else recover(c,st,rp,engine)
        print(json.dumps(result),flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('approved reboot: '+str(exc),file=sys.stderr)
        sys.exit(2)
