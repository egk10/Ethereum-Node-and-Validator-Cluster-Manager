# Manutenção semanal do egkcluster

O executor roda sozinho por `egkcluster-maintenance.timer` no **cloudvero**, domingo às 09:15 em `America/Sao_Paulo`. Ele não depende de uma sessão de terminal, de um modelo local, nem de cron no minipcamd4. Esse servidor saiu do cluster Ethereum e não está na configuração.

## Escopo e ativação

Copiar `scripts/cluster-maintenance.py`, `scripts/gestaobot_client.py` e `config/maintenance.example.json` para `/opt/egkcluster/`, deixando o JSON como `/opt/egkcluster/maintenance.json`. A service usa `User=egk`, portanto `egk` precisa de leitura/escrita de `/opt/egkcluster/state`, da própria configuração, de sua chave SSH para os cinco nós e de `sudo -n docker` e `sudo -n apt-get` no cloudvero. A chave DeepSeek fica em `/opt/egkcluster/maintenance.env`, arquivo separado com permissão restrita (`0600`), na forma `DEEPSEEK_API_KEY=...`. Não copiar nem ler `.env.interno` do GestãoBot. O cliente do bot usa apenas a API local `http://127.0.0.1:8101` e valida essa origem.

O exemplo vem com `enabled: false` e `clients: false`, `os: false` em todos os seis hosts. Habilitar explicitamente a chave geral e cada ação por nó após revisão dos caminhos reais, acesso SSH, sudo e estado de saúde. Portas SSH 2222 valem do cloudvero; a porta 22 é aceita apenas como substituição de teste da estação. Instalar service e timer **apenas** depois da revisão e autorização de publicação. `Persistent=true` executa um horário perdido quando o timer é ativado novamente, sujeito às mesmas travas de estado.

Comandos de avaliação local:

```bash
python3 scripts/cluster-maintenance.py --config config/maintenance.example.json --check
python3 scripts/cluster-maintenance.py --config config/maintenance.example.json --dry-run
python3 -m unittest discover -s tests -p test_maintenance.py
```

`--check` e `--dry-run` fazem somente SSH local/consulta HTTP e leitura de releases GitHub. Não enviam WhatsApp, não chamam DeepSeek, não fazem `apt-get update`, nem atualizam clientes. `--refresh-approvals` consulta o estado de códigos existentes no GestãoBot e persiste a resposta local, sem mandar aviso ou executar reboot. `--run` é a única rota que atualiza nós. O arquivo JSON pode continuar desabilitado para produzir inventário de avaliação. Um erro de SSH, GitHub (inclusive rate limit), LLM, quorum ou comunicação GestãoBot interrompe o ciclo. O aceite do endpoint do GestãoBot prova apenas que a API aceitou o pedido; a entrega do WhatsApp depende dos recibos Meta.

## Decisão por nó

O executor coleta os cinco pares EL/CL e os validadores do cloudvero, que não roda beacon ou EL locais. Cada probe registra montagem do data-root, espaço livre, percentual usado, beacon sync/EL offline dos cinco sources, estado e imagem/ID dos containers, `ethd version`, commit, pins conhecidos, pacotes apt pendentes e arquivo de reboot. Ele consulta releases oficiais de eth-docker, Geth, Nethermind, Prysm, Lighthouse, Lodestar, Nimbus, Vero e Hyperdrive pela API GitHub, incluindo a tag e um trecho de notas de cada release. Compara as referências em inventário; tags mutáveis e pins não garantem versão atual, portanto o relatório não afirma que tudo está atualizado apenas pelo sucesso do comando. O Hyperdrive aparece com imagens e versão de CLI/pacote próprias e atualização pendente de receita separada.

A saúde deve estar completa **antes de cada ação**: seis probes presentes; cada data-root com pelo menos 10 GiB livres e uso abaixo de 80%; nos cinco sources, CL não sincronizando nem otimístico, `el_offline=false` e containers EL/CL em pé; no cloudvero, Vero, web3signer e os containers Hyperdrive configurados em pé, além de atestação Vero publicada nos últimos dez minutos. Pelo menos dois **outros** sources EL/CL saudáveis ficam disponíveis antes de mexer em um nó. A análise DeepSeek Flash envia somente inventário/resumo JSON, devolve `veto`, `summary`, `reason`, e nunca fornece comandos ao executor. Notas de release entram como dados sem confiança e não viram instruções. O JSON é validado estritamente e há uma tentativa adicional após resposta malformada. Um veto ou falha interrompe a execução com alerta.

Para cada nó habilitado, na ordem do JSON, o executor faz:

1. Backup datado de `.env` e guarda estado `mutating` em disco antes do primeiro comando.
2. Para clientes: `ETHD_FRONTEND=noninteractive ./ethd cmd pull --ignore-buildable`, depois `./ethd cmd build --pull` (`--no-cache` quando algum `*_DOCKERFILE` conhecido é `Dockerfile.source`), depois `./ethd up`. `--ignore-buildable` evita tentar baixar tags locais como `geth:local` de um registry. Esse caminho mantém pins existentes e atualiza imagens para a definição atual do compose. Um build de código fonte com target Git fixo permanece nesse target. Não edita fee recipient, chaves, threshold ou fallback.
3. Para OS: `apt-get update` e `DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get --no-remove upgrade`, com timeout de lock. Não executa `autoremove`, `dist-upgrade`, `full-upgrade` nem reboot.
4. Recoleta todos os nós e aguarda o nó alterado voltar a synced, não otimístico, EL online, disco dentro do limite, containers ativos e Vero publicando atestação. Interrompe sem passar ao próximo quando qualquer outro nó perde saúde/quorum ou quando o timeout acaba.

`./ethd update --non-interactive` **não é usado**: a versão local declara que o modo não interativo assume sim para resync/migrações e seu `update` chama `docker system prune --force`. Isso poderia apagar containers intencionalmente parados. A atualização do código do próprio eth-docker e migrações de esquema ficam registradas como pendência de revisão humana; o executor atualiza imagens a partir da definição já instalada. O Hyperdrive requer receita própria e não é alterado. `hyperdrive_sw_operator` e eth-lido permanecem parados por decisão operacional.

Se `/var/run/reboot-required` aparecer após uma ação, o executor abre pedido com código no GestãoBot, consulta o estado da aprovação, persiste `pending_reboots` junto com o `boot_id` e pula o restante das ações **desse nó**. A execução do reboot fica para o operador, seguindo saúde/quorum e um nó por vez. Aprovar o código **não aciona** reboot por este programa. Também não há resync automático. Nos ciclos seguintes, o nó com reboot pendente é pulado; os demais nós elegíveis continuam sujeitos a todas as travas. Um worktree eth-docker alterado também pula apenas o nó afetado e aparece como pendência explícita. Depois de um reboot manual, o próximo ciclo observa mudança de `boot_id`, ausência de `reboot-required`, aprovação registrada e saúde completa; só então conclui o código no GestãoBot, move o registro para `reboot_history` e libera o nó. Sem essa prova, a pendência permanece. Uma execução interrompida durante ou após mutação fica `blocked`: o próximo timer não repete um comando de resultado desconhecido. O estado exige reconciliação humana documentada; não apagar o arquivo para forçar repetição sem investigar.

`/opt/egkcluster/state/maintenance.json` é gravado por substituição atômica, sob `flock` exclusivo no caminho `maintenance.lock`. O estado inclui inventário, ações concluídas, ação corrente, erro e códigos pendentes. Evitar copiar o estado para canais públicos. `journalctl -u egkcluster-maintenance.service` mostra a falha local; o alerta GestãoBot é adicional e seu próprio erro fica no estado.

Fontes: [Eth Docker update](https://ethdocker.com/Support/Update), [Eth Docker GitHub](https://github.com/ethstaker/eth-docker), [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/), [DeepSeek thinking](https://api-docs.deepseek.com/guides/thinking_mode/).
