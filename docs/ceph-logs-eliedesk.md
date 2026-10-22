# Logs enormes do cephadm em eliedesk (Ceph 19.2.3)

FSID `c250c795-7f0b-11f0-8959-3c7c3f7a0e4f`. Cluster Squid 19.2.3, cephadm com Docker, 7 hosts. Este documento só descreve o diagnóstico e os comandos. Nada aqui foi executado nos hosts.

O FSID é um UUID versão 1. O timestamp dele é 2025-08-22 03:54:52 UTC.

## Resumo (pt-BR)

Os dois arquivos cresceram pelo conteúdo que o Ceph 19.2.3 grava o tempo todo, e a rotação `daily` / `rotate 7` / `compress` não impõe teto de tamanho. Não há, no trecho coletado, um loop apertado de inventário.

`ceph-volume.log` (15 GB) é o inventário de discos que o cephadm dispara de propósito. O `ceph-volume` 19.2.3 abre o log em nível `debug` e o módulo `ceph_volume.process` grava cada linha de stdout (`udevadm`, mounts, `lsblk`) em INFO. O cephadm não passa `--log-level`. A opção `mgr/cephadm/ceph_volume_log_level` ainda não existe nesta versão (tracker 73725, sem release). Com o agent desligado, o intervalo efetivo é `mgr/cephadm/device_cache_timeout` (padrão 1800 s). Com o agent ligado, o mesmo inventário roda a cada `mgr/cephadm/agent_refresh_rate` (padrão 20 s).

`ceph-client.ceph-exporter.eliedesk.log` (2.2 GB) é uma linha só, a cada 5 s, para cada daemon local: `pid path is empty; process metrics won't be fetched`. No tail são seis daemons (mds `cephfs.eliedesk.nlpljp`, `mon.eliedesk`, `osd.0`–`osd.3`), cerca de 16 MB/dia. 2.2 GB equivalem a uns 130–145 dias dessa linha. O exporter pede `pid_file` no admin socket; no cephadm o daemon fica em foreground dentro do container e não cria pid file, e o PID namespace do exporter nem veria o processo do OSD. O aviso é esperado. Não existe em 19.2.3 a flag `exporter_enable_process_metrics` (tracker 71991). O subsistema `ceph_exporter` nasce em `1/5`, e a mensagem é `dout(1)`, então `debug_ceph_exporter = 0/5` corta o spam e mantém erros `derr`.

A config de logrotate do cephadm cobre `/var/log/ceph/<fsid>/*.log`, mas só `daily`, sem `maxsize`. O cephadm 19.2.3 também não liga `logrotate.timer` (tracker 70373, backport para Squid ainda aberto, correção só no Tentacle). E o `postrotate` manda SIGHUP para mon/mgr/mds/osd/rgw, não para `ceph-exporter`. Incluir o exporter nesse `killall -1` derruba o daemon: no 19.2.3 o SIGHUP mata o processo (tracker 68721, corrigido só no v20).

O arquivo `/etc/sudoers.d/ceph-smartctl` do pacote tem `*` nos argumentos (`smartctl ... /dev/*` e `nvme * smart-log-add ... /dev/*`). O sudo-rs, padrão no Ubuntu 26.04, recusa wildcard em argumento e descarta a regra. Regex `^...$` também não serve no sudo-rs. O Ceph chama `sudo smartctl -x --json=o /dev/<disco>` e `sudo nvme <vendor> smart-log-add --json /dev/<disco>` (`src/common/blkdev.cc`). A substituição correta é um wrapper em `secure_path` só do usuário `ceph`, mais `dpkg-divert` para o apt não repor o arquivo do pacote.

Ordem sugerida: comandos só de leitura, depois config do exporter e do intervalo de inventário, depois logrotate com teto e timer horário, depois truncar os arquivos grandes sem `logrotate -f` (copiar 15 GB pode encher o disco), por último o sudoers. Cada bloco tem rollback.

## Evidência do tail

Arquivo enviado: tail dos dois logs em 2026-10-22 por volta de 23:20–23:24 UTC.

Inventário, um passe só (o mesmo milissegundo para o dump udev, depois um `findmnt` por device a cada ~60 ms):

```text
[2026-10-22 23:20:16,239][ceph_volume.process][INFO  ] stdout ID_MODEL=TEAM_T2532TB
[2026-10-22 23:20:16,239][ceph_volume.process][INFO  ] stdout ID_WWN=0x0000000000000000
[2026-10-22 23:20:16,239][ceph_volume.process][INFO  ] stdout ID_SERIAL=TEAM_T2532TB_TPBF2401240030201078
[2026-10-22 23:20:16,239][ceph_volume.process][INFO  ] stdout ID_FS_TYPE=ceph_bluestore
[2026-10-22 23:20:16,239][ceph_volume.process][INFO  ] stdout ID_PATH=pci-0000:09:00.0-ata-4.0
[2026-10-22 23:20:16,299][ceph_volume.util.system][INFO  ] /dev/nvme0n1p1 was not found as mounted
[2026-10-22 23:20:16,358][ceph_volume.util.system][INFO  ] /dev/nvme1n1p1 was found as mounted
[2026-10-22 23:20:16,416][ceph_volume.util.system][INFO  ] /dev/nvme1n1p2 was found as mounted
[2026-10-22 23:20:16,473][ceph_volume.util.system][INFO  ] /dev/nvme2n1 was not found as mounted
[2026-10-22 23:20:16,531][ceph_volume.util.system][INFO  ] /dev/nvme3n1 was not found as mounted
[2026-10-22 23:20:16,588][ceph_volume.util.system][INFO  ] /dev/sda was not found as mounted
[2026-10-22 23:20:16,644][ceph_volume.util.system][INFO  ] /dev/sdb was not found as mounted
```

O SSD TEAM T2532TB (serial `TPBF2401240030201078`, BlueStore, ATA na `0000:09:00.0` porta 4) anuncia WWN zerado. Isso atrapalha identidade de disco no Ceph, mas não explica o tamanho do log: o passe acima é um inventário normal, não um retry.

Exporter, ciclo de 5 s (o padrão de `exporter_stats_period`):

```text
2026-10-22T23:24:29.973+0000 7d0de77bc0c0  1 pid path is empty; process metrics won't be fetched for: ceph-mds.cephfs.eliedesk.nlpljp
2026-10-22T23:24:29.979+0000 7d0de77bc0c0  1 pid path is empty; process metrics won't be fetched for: ceph-mon.eliedesk
2026-10-22T23:24:29.993+0000 7d0de77bc0c0  1 pid path is empty; process metrics won't be fetched for: ceph-osd.0
2026-10-22T23:24:30.007+0000 7d0de77bc0c0  1 pid path is empty; process metrics won't be fetched for: ceph-osd.1
2026-10-22T23:24:30.021+0000 7d0de77bc0c0  1 pid path is empty; process metrics won't be fetched for: ceph-osd.2
2026-10-22T23:24:30.034+0000 7d0de77bc0c0  1 pid path is empty; process metrics won't be fetched for: ceph-osd.3
2026-10-22T23:24:35.038+0000 7d0de77bc0c0  1 pid path is empty; process metrics won't be fetched for: ceph-mds.cephfs.eliedesk.nlpljp
```

Conta: 6 linhas × 86400/5 × ~160 bytes ≈ 16 MB/dia. 2.2 GB / 16 MB ≈ 140 dias. Um único dia dessa mensagem não chega a 2.2 GB. O arquivo atual não foi cortado no ritmo `daily`.

O mesmo raciocínio para os 15 GB: se os dois arquivos cobrem a mesma janela, o `ceph-volume.log` escreveu ~110 MB/dia. Um inventário em debug deste host (vários NVMe, `sda`/`sdb`, o TEAM) fica na casa de 1–3 MB. 110 MB/dia é uma passagem a cada ~20–40 min, perto do `device_cache_timeout` de 30 min. Um agent a cada 20 s, com o mesmo tamanho por passe, passaria de 8 GB por dia. Por isso o tail não sustenta um loop apertado; o `use_agent` precisa ser lido no cluster antes de mexer no intervalo.

## Por que a config daily/rotate 7/compress não segurou

Template que o cephadm 19.2.3 grava em `/etc/logrotate.d/ceph-<fsid>` (`cluster.logrotate.config.j2`). Ele só cria o arquivo se ainda não existe (`systemd_unit.py`), então um edit manual sobrevive a redeploy:

```text
# created by cephadm
/var/log/ceph/<fsid>/*.log {
    rotate 7
    daily
    compress
    sharedscripts
    postrotate
        killall -q -1 ceph-mon ceph-mgr ceph-mds ceph-osd ceph-fuse radosgw rbd-mirror cephfs-mirror tcmu-runner || pkill -1 -x "..." || true
    endscript
    missingok
    notifempty
    su root root
}
```

Três limites desse arquivo no 19.2.3:

1. `daily` sem `maxsize`. O logrotate só olha o arquivo quando o timer ou o cron disparam. Entre duas execuções o arquivo pode crescer sem teto. `size` no lugar de `daily` troca o critério; `maxsize` mantém o daily e ainda corta se passar do teto na hora em que o logrotate roda.
2. O timer pode estar desligado. Tracker [70373](https://tracker.ceph.com/issues/70373): o cephadm não faz `systemctl enable --now logrotate.timer` no bootstrap. A correção entrou no main (v20) e o backport Squid [70658](https://tracker.ceph.com/issues/70658) não está no 19.2.3. No Ubuntu o pacote às vezes usa `/etc/cron.daily/logrotate` em vez do timer. Se os dois estão inativos, a config existe e não roda.
3. `ceph-exporter` não está no `killall`. Mesmo com a rotação rodando, o processo segura o fd. No 19.2.3, SIGHUP encerra o exporter (tracker [68721](https://tracker.ceph.com/issues/68721), [67851](https://tracker.ceph.com/issues/67851)). `copytruncate` é o mecanismo que funciona com o binário desta versão: o Ceph abre o log com `O_APPEND`, então o truncate não deixa um arquivo esparso. O `killall` no host também não enxerga processo dentro do Docker, a menos que o container use o PID namespace do host. `copytruncate` não depende desse sinal.

`ceph-volume.log` é escrito por container efêmero (abre, acrescenta, fecha). Rename funcionaria se o logrotate rodasse. O arquivo de 15 GB com esse nome é crescimento desde a última rotação que de fato ocorreu.

## Conferir antes de mudar (somente leitura)

No host admin, com o client admin:

```bash
FSID=c250c795-7f0b-11f0-8959-3c7c3f7a0e4f

ceph versions
ceph config get mgr mgr/cephadm/use_agent
ceph config get mgr mgr/cephadm/agent_refresh_rate
ceph config get mgr mgr/cephadm/device_cache_timeout
ceph config get mgr mgr/cephadm/device_enhanced_scan
ceph config get mgr mgr/cephadm/inventory_list_all
ceph config get client.ceph-exporter.eliedesk debug_ceph_exporter
ceph config get client.ceph-exporter.eliedesk exporter_stats_period
ceph orch ps --daemon-type ceph-exporter
ceph orch ps --daemon-type agent
```

Em eliedesk (e vale repetir nos outros 6 hosts; o mesmo template está em todos):

```bash
FSID=c250c795-7f0b-11f0-8959-3c7c3f7a0e4f
LOGDIR=/var/log/ceph/$FSID

ls -lh "$LOGDIR"/ceph-volume.log* "$LOGDIR"/ceph-client.ceph-exporter.eliedesk.log*
# primeira linha = idade real do inode atual
head -n 1 "$LOGDIR"/ceph-volume.log
head -n 1 "$LOGDIR"/ceph-client.ceph-exporter.eliedesk.log
df -h /var/log /var

systemctl is-enabled logrotate.timer || true
systemctl is-active logrotate.timer || true
systemctl list-timers logrotate.timer --no-pager || true
ls -l /etc/cron.daily/logrotate /etc/cron.hourly 2>/dev/null || true
journalctl -u logrotate.service -n 80 --no-pager || true

# cephadm não sobrescreve este arquivo se ele já existe
cat /etc/logrotate.d/ceph-$FSID
sudo --version
dpkg -S /etc/sudoers.d/ceph-smartctl || true
sed -n '1,20p' /etc/sudoers.d/ceph-smartctl

# o OSD no Docker usa o sudoers da imagem, não o do host,
# a menos que /etc/sudoers.d esteja montado de fora
docker ps --format '{{.Names}}' | grep -F "$FSID" | head
```

Como ler o resultado:

| O que aparecer | Leitura |
| --- | --- |
| Sem `ceph-volume.log.1.gz` (nem `.1`) e `head -n 1` com semanas ou meses | O logrotate não rodou com sucesso. Ligar o timer e o teto é o que segura o disco. |
| Existem `.1.gz`…`.7.gz` e o arquivo atual tem muitos GB com `head -n 1` de hoje | A rotação diária roda, e um dia já passa do aceitável. Aí o intervalo (`use_agent` / `device_cache_timeout`) é o que reduz a taxa. |
| `use_agent` true e `agent_refresh_rate` 20 | Inventário a cada 20 s em todos os hosts. Subir o intervalo. |
| `use_agent` false | Quem agenda o inventário é o mgr, no `device_cache_timeout` (padrão 1800). |
| `device_enhanced_scan` true | Cada passe ainda chama libstoragemgmt (`--with-lsm`). Mais lento e mais log. |
| `sudo --version` contém `sudo-rs` | As linhas com `*` estão descartadas. O wrapper abaixo é o formato válido. |
| `sudo --version` é o sudo do Todd Miller | O arquivo do pacote ainda é aceito (com o risco conhecido do `*` em argumento). O warning citado no pedido é o texto do sudo-rs, então eliedesk está no primeiro caso. |

`mgr/devicehealth/scrape_frequency` (padrão 86400) coleta SMART uma vez por dia via `ceph tell ... smart`. Isso não alimenta o `ceph-volume.log`.

## Correção

Aplicar a config do mgr uma vez. Logrotate, timer e sudoers são por host. Fazer eliedesk primeiro e, se `df` dos outros hosts mostrar o mesmo padrão, repetir.

### 1. Calar o spam do exporter

`debug_ceph_exporter 0/5` tira do arquivo as mensagens de nível 1 (incluindo pid vazio e falha de asok em nível 1) e deixa a memória em 5. `derr` continua. Métricas Prometheus seguem; o que deixa de existir são as métricas de processo (`ceph_exporter_cpu_*`, faults, RSS), que neste deploy já não eram coletadas.

```bash
ceph config set client.ceph-exporter debug_ceph_exporter 0/5
ceph config get client.ceph-exporter.eliedesk debug_ceph_exporter
```

A seção `client.ceph-exporter` vale para `client.ceph-exporter.<host>` em todos os hosts. O id no nome do log é `eliedesk`. Se `ceph orch ps --daemon-type ceph-exporter` mostrar outro id, usar esse id no lugar de `eliedesk` daqui em diante, inclusive em `agent.<id>/agent.json`.

Se o get não mostrar `0/5`, gravar o nome completo:

```bash
ceph config set client.ceph-exporter.eliedesk debug_ceph_exporter 0/5
```

O exporter do 19.2.3 nem sempre aplica `debug_*` sem reinício. Esperar 15 s e contar linhas novas. Se continuarem:

```bash
ceph orch daemon restart ceph-exporter.eliedesk
```

Não mandar SIGHUP. No 19.2.3 isso encerra o container e o orch marca o daemon down até o restart.

Não subir `exporter_stats_period` para “resolver” o log. O padrão 5 s é o período das métricas. Não existe `exporter_enable_process_metrics` nesta versão; `ceph config set` dessa chave falha.

Rollback:

```bash
ceph config rm client.ceph-exporter debug_ceph_exporter
ceph config rm client.ceph-exporter.eliedesk debug_ceph_exporter
ceph orch daemon restart ceph-exporter.eliedesk
```

### 2. Diminuir a frequência do inventário

Só depois de ler `use_agent`. Não há como baixar o nível do `ceph-volume.log` por config no 19.2.3: o default de `--log-level` no `ceph_volume/main.py` é `debug`, o cephadm chama `inventory --format=json` sem `--log-level`, e `CEPH_VOLUME_DEBUG=1` no container só reergue exceção no decorator, não muda o handler. `ceph config set mgr mgr/cephadm/ceph_volume_log_level warning` responde que a opção não existe.

Agent ligado (o valor 600 s é 10 min; o padrão de fábrica é 20):

```bash
ceph config get mgr mgr/cephadm/agent_refresh_rate
ceph config set mgr mgr/cephadm/agent_refresh_rate 600
```

O agent só passa a usar o valor novo quando o `agent.json` é reescrito. Conferir em eliedesk:

```bash
FSID=c250c795-7f0b-11f0-8959-3c7c3f7a0e4f
python3 -c 'import json; print(json.load(open("/var/lib/ceph/'"$FSID"'/agent.eliedesk/agent.json"))["refresh_period"])'
```

Se continuar 20 depois de um ciclo do mgr (~`host_check_interval`, padrão 600 s):

```bash
ceph orch daemon redeploy agent.eliedesk
```

Agent desligado. O cache de devices padrão é 1800 s. 21600 s (6 h) corta a taxa em cerca de 8 vezes. Disco novo ou OSD zap pode levar até esse tempo para aparecer em `ceph orch device ls`; `--refresh` força um passe:

```bash
ceph config get mgr mgr/cephadm/device_cache_timeout
ceph config set mgr mgr/cephadm/device_cache_timeout 21600
```

Se `device_enhanced_scan` estiver true e ninguém usa os campos do libstoragemgmt:

```bash
ceph config set mgr mgr/cephadm/device_enhanced_scan false
```

Deixar `inventory_list_all` como está, a menos que o get mostre true sem necessidade. True inclui mapper, LV e partição no JSON e aumenta o log.

Rollback:

```bash
ceph config set mgr mgr/cephadm/agent_refresh_rate 20
ceph config set mgr mgr/cephadm/device_cache_timeout 1800
ceph config set mgr mgr/cephadm/device_enhanced_scan false
ceph orch daemon redeploy agent.eliedesk
```

O último `redeploy` só se o agent existir. `device_enhanced_scan false` é o default; se o get original era true, voltar para true.

### 3. Teto de tamanho no logrotate

Editar o arquivo que o cephadm já criou. Como o arquivo existe, o próximo deploy não o regrava. Se alguém apagar o arquivo, o cephadm recria a versão sem `maxsize`; o timer horário abaixo continua chamando o que estiver no disco.

`copytruncate` é de propósito: o exporter 19.2.3 não reabre o log em SIGHUP, e SIGHUP mata o processo. O `postrotate` abaixo é o mesmo conjunto de binários do template 19.2.3, sem `ceph-exporter`.

Em eliedesk, como root. Trocar o arquivo inteiro (guardar o antigo no `.bak`):

```bash
FSID=c250c795-7f0b-11f0-8959-3c7c3f7a0e4f
install -m 0644 /etc/logrotate.d/ceph-$FSID /etc/logrotate.d/ceph-$FSID.bak.$(date +%Y%m%d)

cat > /etc/logrotate.d/ceph-$FSID << EOF
# created by cephadm, edit local (19.2.3 não regrava se o arquivo existe)
# maxsize exige que o logrotate rode mais de uma vez por dia; ver ceph-logrotate-size.timer
/var/log/ceph/${FSID}/*.log {
    daily
    rotate 7
    maxsize 100M
    compress
    delaycompress
    missingok
    notifempty
    su root root
    copytruncate
    sharedscripts
    postrotate
        killall -q -1 ceph-mon ceph-mgr ceph-mds ceph-osd ceph-fuse radosgw rbd-mirror cephfs-mirror tcmu-runner || pkill -1 -x "ceph-mon|ceph-mgr|ceph-mds|ceph-osd|ceph-fuse|radosgw|rbd-mirror|cephfs-mirror|tcmu-runner" || true
    endscript
}
EOF

logrotate -d /etc/logrotate.d/ceph-$FSID
```

O `-d` é dry-run. Conferir se ele menciona os dois arquivos e se não reclama de `su` ou de duplicata (dois arquivos em `/etc/logrotate.d` casando o mesmo path fazem o logrotate pular os dois).

Timer horário, para o `maxsize` valer antes da meia-noite. Não usar `logrotate -f` aqui: `-f` gira todo hora e só guarda 7 horas.

```bash
FSID=c250c795-7f0b-11f0-8959-3c7c3f7a0e4f

cat > /etc/systemd/system/ceph-logrotate-size.service << EOF
[Unit]
Description=Rotate Ceph logs when they pass maxsize
ConditionPathExists=/etc/logrotate.d/ceph-${FSID}

[Service]
Type=oneshot
ExecStart=/usr/sbin/logrotate /etc/logrotate.d/ceph-${FSID}
EOF

cat > /etc/systemd/system/ceph-logrotate-size.timer << EOF
[Unit]
Description=Hourly check of Ceph log sizes

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=5m

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now ceph-logrotate-size.timer
systemctl enable --now logrotate.timer || true
systemctl list-timers 'ceph-logrotate-size.timer' 'logrotate.timer' --no-pager
```

`logrotate.timer` pode não existir em instalação que só tem cron.daily. Se o enable falhar, o timer horário novo ainda aplica `daily` + `maxsize` porque o logrotate guarda estado em `/var/lib/logrotate/status`.

Repetir o bloco nos outros hosts. O FSID é o mesmo.

Rollback:

```bash
FSID=c250c795-7f0b-11f0-8959-3c7c3f7a0e4f
systemctl disable --now ceph-logrotate-size.timer || true
rm -f /etc/systemd/system/ceph-logrotate-size.service /etc/systemd/system/ceph-logrotate-size.timer
systemctl daemon-reload
cp -a /etc/logrotate.d/ceph-$FSID.bak.<data> /etc/logrotate.d/ceph-$FSID
```

Não desligar `logrotate.timer` no rollback se ele já estava enabled antes. O `|| true` do enable não guarda o estado anterior; anotar a saída do `is-enabled` da seção de leitura.

### 4. Devolver o espaço já ocupado

`logrotate -f` com `copytruncate` copia o arquivo antes de truncar. 15 GB de cópia mais a compressão precisam de espaço livre da mesma ordem. Se `df -h /var` mostrar menos que ~20 GB livres, não forçar a rotação. Truncar direto.

`ceph-volume.log` não fica aberto entre os passes:

```bash
FSID=c250c795-7f0b-11f0-8959-3c7c3f7a0e4f
LOGDIR=/var/log/ceph/$FSID
ls -lh "$LOGDIR"/ceph-volume.log
truncate -s 0 "$LOGDIR"/ceph-volume.log
ls -lh "$LOGDIR"/ceph-volume.log
```

Exporter: achar o pid no host (o processo está no container; o fd é do inode bind-mounted). Truncar e, se o tamanho voltar na hora para vários GB, o fd não estava em `O_APPEND` e o arquivo ficou esparso. Nesse caso, reiniciar o daemon e truncar de novo com o processo parado.

```bash
FSID=c250c795-7f0b-11f0-8959-3c7c3f7a0e4f
LOG=/var/log/ceph/$FSID/ceph-client.ceph-exporter.eliedesk.log

# pid dentro do container, visto do host se o docker não isola o fd do host
# conferir qual inode o processo ainda escreve
docker ps --format '{{.ID}} {{.Names}}' | grep exporter | grep eliedesk
# substituir CID
docker top <CID> -eo pid,cmd
# no host, para o PID do ceph-exporter mostrado por docker top (pode ser o PID do container namespace;
# ls -l /proc/<hostpid>/fd funciona quando o docker top mostra o PID do host)
truncate -s 0 "$LOG"
sleep 12
ls -lh "$LOG"
tail -n 3 "$LOG"
```

Se depois do `debug_ceph_exporter 0/5` e do restart o `tail` ainda mostrar `pid path is empty` a cada 5 s, o daemon não releu a config: `ceph orch daemon restart ceph-exporter.eliedesk` de novo e repetir o truncate.

Depois de uma hora, `ls -lh` deve mostrar os dois arquivos bem abaixo de 100 MB. O exporter, com nível 0, deve ficar quase parado. O `ceph-volume.log` sobe alguns MB por passe e o timer corta em 100 MB.

Não há rollback do truncate. O conteúdo era repetição de inventário e da mesma linha de pid. Se precisar de uma amostra, copiar 20 MB do final antes do truncate:

```bash
tail -c 20M "$LOGDIR"/ceph-volume.log > /root/ceph-volume.log.sample
tail -c 2M "$LOG" > /root/ceph-exporter.eliedesk.log.sample
```

## sudoers do smartctl

O arquivo do pacote em 19.2.3 (`sudoers.d/ceph-smartctl`):

```text
# allow ceph daemons (which run as user ceph) to collect device health metrics
ceph ALL=NOPASSWD: /usr/sbin/smartctl -x --json=o /dev/*
ceph ALL=NOPASSWD: /usr/sbin/nvme * smart-log-add --json /dev/*
```

O sudo-rs emite, em todo `sudo`:

```text
/etc/sudoers.d/ceph-smartctl:3:20: wildcards are not allowed in command arguments
```

A regra inteira é ignorada. O Ceph não chama esses binários pelo path absoluto. Em `src/common/blkdev.cc` o argv é:

```text
sudo smartctl -x --json=o /dev/<devname>
sudo nvme <vendor> smart-log-add --json /dev/<devname>
```

`<vendor>` sai de `ID_VENDOR` em minúsculas (no TEAM do tail, `ID_VENDOR=ATA`, então `ata`). O sudo resolve o nome pelo `secure_path`. Dá para pôr um wrapper nesse path só para o usuário `ceph`, sem trocar o `smartctl` que o root usa no shell.

O sudoers da imagem Docker é outro arquivo, com o sudo clássico do container, que ainda aceita `*`. O warning no host vem do sudo do host lendo o arquivo do host. SMART dos OSDs só passa a usar o wrapper se `/etc/sudoers.d` (e o diretório do wrapper) estiver montado dentro do container, ou se o scrape rodar no host. Conferir com `docker inspect` os mounts de um `osd.*` de eliedesk. Mesmo quando o SMART do container não depende deste arquivo, o arquivo inválido suja o stderr de todo `sudo` no host.

Wrappers. Argumento fora do formato que o `blkdev.cc` usa sai com status 2 e não chega no binário real.

```bash
install -d -m 0755 /usr/local/libexec/ceph-smart

cat > /usr/local/libexec/ceph-smart/smartctl << 'EOF'
#!/bin/sh
set -eu
if [ "$#" -eq 3 ] && [ "$1" = "-x" ] && [ "$2" = "--json=o" ]; then
    dev=$3
    case $dev in
        /dev/*) ;;
        *) echo "ceph-smartctl: device must be /dev/..." >&2; exit 2 ;;
    esac
    rest=${dev#/dev/}
    case $rest in
        .|..|*..*|*[!A-Za-z0-9_.-]*) echo "ceph-smartctl: rejected device" >&2; exit 2 ;;
    esac
    exec /usr/sbin/smartctl -x --json=o "$dev"
fi
echo "ceph-smartctl: only -x --json=o /dev/<disk> is allowed" >&2
exit 2
EOF

cat > /usr/local/libexec/ceph-smart/nvme << 'EOF'
#!/bin/sh
set -eu
if [ "$#" -eq 4 ] && [ "$2" = "smart-log-add" ] && [ "$3" = "--json" ]; then
    vendor=$1
    dev=$4
    if [ -z "$vendor" ]; then
        echo "ceph-nvme: empty vendor" >&2
        exit 2
    fi
    case $vendor in
        *[!A-Za-z0-9_.-]*) echo "ceph-nvme: rejected vendor" >&2; exit 2 ;;
    esac
    case $dev in
        /dev/*) ;;
        *) echo "ceph-nvme: device must be /dev/..." >&2; exit 2 ;;
    esac
    rest=${dev#/dev/}
    case $rest in
        .|..|*..*|*[!A-Za-z0-9_.-]*) echo "ceph-nvme: rejected device" >&2; exit 2 ;;
    esac
    if [ -x /usr/sbin/nvme ]; then
        real=/usr/sbin/nvme
    elif [ -x /usr/bin/nvme ]; then
        real=/usr/bin/nvme
    else
        echo "ceph-nvme: nvme binary not found" >&2
        exit 127
    fi
    exec "$real" "$vendor" smart-log-add --json "$dev"
fi
echo "ceph-nvme: only <vendor> smart-log-add --json /dev/<disk> is allowed" >&2
exit 2
EOF

chown root:root /usr/local/libexec/ceph-smart/smartctl /usr/local/libexec/ceph-smart/nvme
chmod 0755 /usr/local/libexec/ceph-smart/smartctl /usr/local/libexec/ceph-smart/nvme
```

Sudoers. `Defaults:ceph secure_path` faz o `sudo smartctl` do usuário `ceph` achar o wrapper antes de `/usr/sbin`. Root e os outros usuários seguem o `secure_path` global.

Se o arquivo veio do pacote, desviar o path para o apt não repor as linhas com `*` no próximo upgrade do `ceph-base`:

```bash
if dpkg -S /etc/sudoers.d/ceph-smartctl >/dev/null 2>&1; then
    dpkg-divert --local --rename \
        --divert /etc/sudoers.d/ceph-smartctl.packaged \
        --add /etc/sudoers.d/ceph-smartctl
fi

cat > /etc/sudoers.d/ceph-smartctl.new << 'EOF'
# Ceph device health (blkdev.cc). sudo-rs rejeita '*' em argumento.
# O usuário ceph só alcança estes wrappers; eles executam o binário real.
Defaults:ceph secure_path="/usr/local/libexec/ceph-smart:/usr/sbin:/usr/bin:/sbin:/bin"
ceph ALL=(root) NOPASSWD: /usr/local/libexec/ceph-smart/smartctl
ceph ALL=(root) NOPASSWD: /usr/local/libexec/ceph-smart/nvme
EOF

visudo -cf /etc/sudoers.d/ceph-smartctl.new
install -m 0440 -o root -g root /etc/sudoers.d/ceph-smartctl.new /etc/sudoers.d/ceph-smartctl
rm -f /etc/sudoers.d/ceph-smartctl.new
visudo -c
```

Se `visudo -cf` falhar, não instalar. O `.new` fica para inspeção.

Prova, ainda em eliedesk. O teste negativo usa uma flag que o wrapper recusa; não usar `smartctl -s`, que altera o disco se o wrapper estiver errado.

```bash
# não pode mais aparecer "wildcards are not allowed"
sudo -n true

# forma que o OSD usa. smartctl pode devolver erro próprio do disco;
# o que não pode aparecer é "not allowed" nem pedido de senha.
sudo -u ceph sudo -n smartctl -x --json=o /dev/sda ; echo smartctl_exit:$?

# o wrapper tem de recusar antes de exec
sudo -u ceph sudo -n smartctl --not-allowed /dev/sda ; echo rejected_exit:$?

sudo -u ceph sudo -n nvme ata smart-log-add --json /dev/nvme0n1 ; echo nvme_exit:$?
sudo -l -U ceph
```

`rejected_exit` tem de ser 2 e a mensagem `only -x --json=o`. `smartctl_exit` 0 é SMART ok; 1 ou 2 vindo do próprio smartctl (dispositivo sem SMART) também é aceitável desde que o stderr não seja `sorry` / `a password is required` / `not allowed`.

No container, só se o inspect mostrar sudoers do host montado, ou se `ceph device scrape-daemon-health-metrics osd.0` continuar com `sudo: exit status: 1` e o stderr do host já estiver limpo. Aí o sudo de dentro da imagem também é sudo-rs e o mesmo wrapper precisa existir no rootfs do container. A imagem `quay.io/ceph/ceph:v19.2.3` traz sudo clássico; o caso esperado é o warning ficar só no host.

Rollback do sudoers:

```bash
rm -f /etc/sudoers.d/ceph-smartctl
if [ -f /etc/sudoers.d/ceph-smartctl.packaged ]; then
    dpkg-divert --local --rename --remove /etc/sudoers.d/ceph-smartctl
fi
rm -rf /usr/local/libexec/ceph-smart
visudo -c
```

Isso devolve o arquivo do pacote, com os wildcards, se o divert foi feito. O warning do sudo-rs volta junto.

## O que fica de fora

- Não dá para desligar o log de inventário por `ceph config` no 19.2.3. Frequência menor e `maxsize` são o controle disponível. A opção do tracker 73725, quando sair num release, será o nível do log.
- WWN `0x0000000000000000` no TEAM T2532TB fica registrado. Não é a causa dos 15 GB. Vale um `ceph device ls` / `ceph orch device ls eliedesk --refresh` depois, para ver se o disco aparece duplicado ou sem id estável.
- Não alterar imagem, não reiniciar OSD/MON/MDS, não rodar `logrotate -f` com o arquivo de 15 GB se o filesystem estiver apertado.

## Referências

- ceph-volume 19.2.3: `--log-level` default `debug` em `src/ceph-volume/ceph_volume/main.py`; cada linha de stdout em INFO em `src/ceph-volume/ceph_volume/process.py` (`logfile_verbose` default true).
- cephadm 19.2.3: `get_ceph_volume_container` exporta `CEPH_VOLUME_DEBUG=1`; o agent chama `inventory --format=json` a cada `refresh_period` (`agent_refresh_rate`, default 20). Sem agent, `device_cache_timeout` default 1800.
- Exporter 19.2.3: `dout(1)` em `DaemonMetricCollector.cc`; `SUBSYS(ceph_exporter, 1, 5)`; `exporter_stats_period` default 5. Trackers [71991](https://tracker.ceph.com/issues/71991) e [74859](https://tracker.ceph.com/issues/74859).
- SIGHUP mata o exporter até o v20: [68721](https://tracker.ceph.com/issues/68721).
- `logrotate.timer` não é habilitado pelo cephadm 19.2.3: [70373](https://tracker.ceph.com/issues/70373), backport [70658](https://tracker.ceph.com/issues/70658).
- sudoers do pacote: `sudoers.d/ceph-smartctl` no tag `v19.2.3`. sudo-rs: wildcards em argumento são recusados; `*` só como último argumento significando “o resto”. Regex em argumento não é suportado (sudo-rs issue 1350).
