#!/usr/bin/env python3
"""Run the authorized Hyperdrive Lodestar pilot under the shared maintenance lock."""
import argparse
import fcntl
import importlib.util
import json
import sys
import time
from pathlib import Path

from gestaobot_client import Client
import hyperdrive_vc as h

spec = importlib.util.spec_from_file_location('maintenance',Path(__file__).with_name('cluster-maintenance.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def run(c):
    st = m.State(Path(c['state_file']))
    if st.value.get('status') in ('running','blocked'):
        raise m.MaintenanceError('Previous maintenance requires reconciliation')
    report = m.State(Path(c['state_file']).parent / 'hyperdrive-pilot-20261003.json')
    if report.value.get('status'):
        raise m.MaintenanceError('Pilot report already exists; inspect it before repeating any action')
    backend, bot = m.Backend(c), Client()
    engine = m.Engine(c,backend,bot,st)
    inventory = engine.probe_all()
    issues = m.health(inventory,c)
    if issues:
        raise m.MaintenanceError('Hyperdrive preflight health: ' + '; '.join(issues))
    releases = backend.releases()
    blockers = m.hyperdrive_blockers(inventory['cloudvero'],releases)
    prior = m.hyperdrive_comparison(inventory['cloudvero'],releases)['lodestar']
    if blockers or prior['installed'] != '1.48.0' or m.semver(prior['latest']) != (1,49,0):
        raise m.MaintenanceError('This pilot reviews exactly Hyperdrive 1.3.0 / Lodestar 1.48.0 -> 1.49.0')
    llm = backend.llm(m.inventory_report(inventory,releases,c),releases)
    if llm['veto']:
        raise m.MaintenanceError('LLM veto: ' + llm['reason'])
    previous = json.loads(json.dumps(st.value))
    report.value = {'status':'running','phase':'preflight','started_at':m.now(),
                    'prior':prior,'releases':releases,'llm':llm,'inventory_before':inventory,
                    'previous_maintenance_status':previous.get('status')}
    report.save()
    st.value.update(status='running',phase='hyperdrive-pilot/applying',
                    current={'node':'cloudvero','kind':'hyperdrive','report':str(report.path)})
    st.save()
    try:
        report.value['start_notification'] = engine.alert('Hyperdrive: atualização iniciando','cloudvero',
            'Somente Lodestar VC 1.48.0 para 1.49.0. Banco de proteção contra slashing, diretórios, '
            'configuração e demais containers preservados. Cinco sources saudáveis antes de aplicar.')
        report.save()
        result = backend.action(c['nodes']['cloudvero'],'hyperdrive',expected_versions={'lodestar':prior})
        since = time.time()
        report.value.update(phase='postcheck',action=result,postcheck_since=since)
        report.save()
        st.value.update(phase='hyperdrive-pilot/postcheck')
        st.save()
        after = engine.postcheck('cloudvero',since)
        for _ in range(2):
            time.sleep(60)
            after = engine.probe_all()
            issues = m.health(after,c,attestation_since=since)
            if issues:
                raise m.MaintenanceError('Hyperdrive observation health: ' + '; '.join(issues))
        if (h.version(after['cloudvero']['hyperdrive_vc_version']) != '1.49.0'
                or after['cloudvero']['containers'][h.VC]['image_id'] != result['candidate_versions']['lodestar']['image_id']
                or h.settings_hashes() != result['settings_hashes']):
            raise m.MaintenanceError('Hyperdrive version/image/settings changed during observation')
        live = h.inspect_all()
        for name, expected in result['protected_containers'].items():
            if name not in live or h.identity(live[name]) != expected:
                raise m.MaintenanceError('Hyperdrive observation changed non-target container: ' + name)
        report.value.update(status='complete',phase='complete',finished_at=m.now(),health_issues=[],
                            inventory_after=after,
                            comparison_after=m.hyperdrive_comparison(after['cloudvero'],releases))
        report.save()
        report.value['end_notification'] = engine.alert('Hyperdrive: atualização concluída','cloudvero',
            'Lodestar VC 1.49.0 confirmado por versão e imagem. Vero e Hyperdrive publicaram novas '
            'atestações após a aplicação; cinco sources sincronizados, não otimistas e EL online. '
            'Demais containers e configuração preservados. Reboot do cloudvero ainda pendente.')
        report.save()
        st.value = previous
        st.value['inventory_after'] = m.inventory_report(after,releases,c)
        st.value['gaps_summary'] = {n:r['gaps'] for n,r in st.value['inventory_after'].items() if r['gaps']}
        st.value['last_hyperdrive_pilot'] = {'report':str(report.path),'completed_at':m.now(),
                                         'version':'1.49.0','image_id':live[h.VC]['Image']}
        st.value.update(status='partial' if st.value.get('pending_reboots') or st.value['gaps_summary'] else 'complete',
                        phase='done',finished_at=m.now())
        st.value.pop('current',None)
        st.save()
        return {'status':'complete','version':'1.49.0','report':str(report.path)}
    except Exception as exc:
        report.value.update(status='blocked',error=str(exc),failed_at=m.now())
        report.save()
        st.value.update(status='blocked',error=str(exc),phase='hyperdrive-pilot/blocked')
        st.save()
        try:
            engine.alert('Hyperdrive: atualização interrompida','cloudvero',str(exc))
        except Exception:
            pass
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config',type=Path,required=True)
    args = ap.parse_args()
    c = m.checked_config(args.config)
    if not c['enabled']:
        raise m.MaintenanceError('Explicit enabled configuration required')
    with Path(c['lock_file']).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(run(c)),flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('hyperdrive pilot: ' + str(exc),file=sys.stderr)
        sys.exit(2)
