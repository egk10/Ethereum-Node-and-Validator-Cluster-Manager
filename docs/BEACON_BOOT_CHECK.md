# Checagem automática do beacon (minipcamd3)

Script e timer systemd que observam o Lodestar (consensus) via Beacon API e reiniciam apenas o serviço `consensus` do eth-docker quando detectam travamento ou lag persistente. Não mexe em validadores (Vero, web3signer).

## Comportamento

| Caminho | Condição | Ação |
|--------|-----------|------|
| **Lag** | `is_syncing=true` e `sync_distance` > 32 por ≥ 30 min (entre execuções do timer) | `docker compose restart consensus` (sem checar `eth_syncing` / `el_offline`) |
| **Travamento** | `is_syncing=true`, head avança < 5 slots em 180 s, EL com `eth_syncing=false` e `el_offline=false` | Mesmo reinício |

Limites persistentes em `/var/lib/beacon-boot-check/state`: cooldown de 30 min após qualquer reinício e no máximo 2 reinícios por dia (UTC), somando os dois caminhos.

## Instalação no host

```bash
sudo install -m 755 scripts/beacon-boot-check.sh /usr/local/bin/beacon-boot-check.sh
sudo install -m 644 systemd/beacon-boot-check.service /etc/systemd/system/
sudo install -m 644 systemd/beacon-boot-check.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now beacon-boot-check.timer
```

O timer dispara 15 min após o boot e a cada 10 min depois. Logs: `journalctl -u beacon-boot-check.service`.

## Testes locais

```bash
chmod +x scripts/beacon-boot-check.sh scripts/test-beacon-boot-check.sh
./scripts/test-beacon-boot-check.sh
```

Simulação: `DRY_RUN=1`, `FAKE_CL1` / `FAKE_CL2` / `FAKE_EL`, `FAKE_NOW` (epoch UTC), `BEACON_BOOT_CHECK_STATE_DIR` (diretório temporário).