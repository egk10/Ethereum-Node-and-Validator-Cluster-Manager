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

O executor coleta os cinco pares EL/CL e os validadores do cloudvero, que não roda beacon ou EL locais. Cada probe registra montagem do data-root, espaço livre, percentual usado, beacon sync/EL offline dos cinco sources, estado e imagem/ID dos containers, `ethd version`, commit, pins conhecidos, pacotes apt pendentes e arquivo de reboot. Ele consulta releases oficiais de eth-docker, Geth, Nethermind, Prysm, Lighthouse, Lodestar, Nimbus, Vero e Hyperdrive pela API GitHub, incluindo a tag e um trecho de notas de cada release. Extrai as versões em execução de EL/CL/Vero e compara com as tags oficiais. Se a versão instalada ou release for desconhecida, diferir em major ou estiver à frente da release consultada, pula a ação de **clientes** nesse nó e registra revisão pendente; uma ação de OS habilitada ainda pode ocorrer com todos os gates de saúde. Por exemplo, Nethermind 1.39.3 → 2.1.0 fica fora da atualização automática. Tags mutáveis e pins não garantem a nova versão, portanto o relatório pós-ação compara as versões observadas e não afirma que tudo está atualizado apenas pelo sucesso do comando. O Hyperdrive aparece com imagens e versão de CLI/pacote próprias e atualização pendente de receita separada.

A saúde deve estar completa **antes de cada ação**: seis probes presentes; cada data-root com pelo menos 10 GiB livres e uso abaixo de 80%; nos cinco sources, CL não sincronizando nem otimístico, `el_offline=false` e containers EL/CL em pé; no cloudvero, Vero, web3signer e os containers Hyperdrive configurados em pé, além de publicações de Vero e `hyperdrive_sw_vc` nos últimos 15 minutos. A janela cobre o intervalo possível entre duties de épocas consecutivas. A pós-checagem exige novas publicações dos dois VCs **após o comando de atualização terminar** e após o `StartedAt` atual de cada container; mensagens antigas não liberam o próximo nó. Todos os cinco sources devem estar synced e não otimísticos antes de qualquer ação seguinte, com pelo menos dois **outros** pares EL/CL saudáveis. A análise DeepSeek Flash envia somente inventário/resumo JSON, devolve `veto`, `summary`, `reason` em português brasileiro conciso, e nunca fornece comandos ao executor. Notas de release entram como dados sem confiança e não viram instruções. O JSON é validado estritamente e há uma tentativa adicional após resposta malformada. Um veto ou falha interrompe a execução com alerta.

Para cada nó habilitado, na ordem do JSON, o executor faz:

1. Backup datado de `.env` e guarda estado `mutating` em disco antes do primeiro comando.
2. Para clientes: `ETHD_FRONTEND=noninteractive ./ethd cmd pull --ignore-buildable`, depois `./ethd cmd build --pull` (`--no-cache` quando algum `*_DOCKERFILE` conhecido é `Dockerfile.source`). **Antes** de subir a stack, executa apenas os binários `--version` das imagens locais recém-construídas em containers descartáveis, sem rede, volumes da stack ou ambiente da stack, e compara o major instalado e a release esperada. Declarações `VOLUME` da própria imagem são substituídas por tmpfs efêmeros, sem montar dados do host. Major novo, versão desconhecida ou divergência da release sem pin fixo bloqueiam a aplicação. Um pin fixo permite versão antiga do mesmo major, que continua visível como gap. Confere novamente os IDs das tags locais e só então usa `./ethd cmd up -d --no-build --pull never`; `ethd up` simples passaria `--remove-orphans` e poderia remover containers parados. `--ignore-buildable` evita tentar baixar tags locais como `geth:local` de um registry. Esse caminho mantém pins existentes e atualiza imagens para a definição atual do compose. Um build de código fonte com target Git fixo permanece nesse target. Não edita fee recipient, chaves, threshold ou fallback.
3. Para OS nos cinco sources: `apt-get update` e `DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get --no-remove upgrade`, com timeout de lock. No cloudvero, após `apt-get update`, lê a lista de pacotes atualizáveis, remove Hyperdrive da seleção, simula a transação para bloquear qualquer atualização transitiva de Hyperdrive ou remoção, e aplica somente a lista restante via `apt-get --only-upgrade --no-remove install`. Lista vazia encerra sem instalar. O pacote Hyperdrive fica como pendência separada porque seu `postinst` pode ligar o operator intencionalmente parado. Não executa `autoremove`, `dist-upgrade`, `full-upgrade` nem reboot.
4. Recoleta todos os nós e aguarda o nó alterado voltar a synced, não otimístico, EL online, disco dentro do limite, containers ativos e Vero publicando atestação. Interrompe sem passar ao próximo quando qualquer outro nó perde saúde/quorum ou quando o timeout acaba.

`./ethd update --non-interactive` **não é usado**: a versão local declara que o modo não interativo assume sim para resync/migrações e seu `update` chama `docker system prune --force`. Isso poderia apagar containers intencionalmente parados. A atualização do código do próprio eth-docker e migrações de esquema ficam registradas como pendência de revisão humana; o executor atualiza imagens a partir da definição já instalada. O Hyperdrive requer receita própria e não é alterado. `hyperdrive_sw_operator` e eth-lido permanecem parados por decisão operacional.

Se `/var/run/reboot-required` aparecer após uma ação, o executor abre pedido com código no GestãoBot, consulta o estado da aprovação, persiste `pending_reboots` junto com o `boot_id` e pula o restante das ações **desse nó**. A execução do reboot fica para o operador, seguindo saúde/quorum e um nó por vez. Aprovar o código **não aciona** reboot por este programa. Também não há resync automático. Nos ciclos seguintes, o nó com reboot pendente é pulado; os demais nós elegíveis continuam sujeitos a todas as travas. Um worktree eth-docker alterado também pula apenas o nó afetado e aparece como pendência explícita. Depois de um reboot manual, o próximo ciclo observa mudança de `boot_id`, ausência de `reboot-required`, aprovação registrada e saúde completa; só então conclui o código no GestãoBot, move o registro para `reboot_history` e libera o nó. Sem essa prova, a pendência permanece. Uma execução interrompida durante ou após mutação fica `blocked`: o próximo timer não repete um comando de resultado desconhecido. O estado exige reconciliação humana documentada; não apagar o arquivo para forçar repetição sem investigar.

`/opt/egkcluster/state/maintenance.json` é gravado por substituição atômica, sob `flock` exclusivo no caminho `maintenance.lock`. O estado inclui inventário, ações concluídas, ação corrente, erro e códigos pendentes. Evitar copiar o estado para canais públicos. `journalctl -u egkcluster-maintenance.service` mostra a falha local; o alerta GestãoBot é adicional e seu próprio erro fica no estado.

## Ativação verificada em 3 de outubro de 2026 (UTC)

Código do executor e monitores publicado em `000fc4d`; ponte GestãoBot publicada e aplicada pelo autodeploy em `4f159a1` no repo Integratech. Os checkouts locais foram integrados por fast-forward, preservando os documentos já alterados e os três scripts originais em `/home/egk/ethereum-maintenance-backup-20261002/`.

No cloudvero, `/opt/egkcluster/maintenance.json` tem a rotina e as ações comuns habilitadas; `/opt/egkcluster/maintenance.env` pertence a `egk`, modo `0600`, com a última chave fornecida pelo usuário. A chamada real ao `deepseek-flash`, esforço baixo e teto 4096, terminou com `finish_reason=stop` e JSON estrito válido em português. O teto anterior de 1500 interrompia a resposta antes de fechar o JSON; respostas incompletas continuam sendo recusadas.

Os três timers estão ativos e habilitados: saúde diária, atestações a cada três minutos e manutenção semanal. A primeira manutenção está agendada para **4 de outubro de 2026, 09:15 São Paulo / 12:15 UTC**. A validação desta implantação fez inventário e probes isoladas; as atualizações dos nós serão executadas pelo timer. A checagem do runtime encontrou seis hosts saudáveis; saúde diária terminou com código 0 e seu resumo recebeu recibo Meta `delivered`. O teste de WhatsApp recebeu `read`. Os hashes dos cinco scripts instalados coincidem com o código versionado e estão registrados em `/opt/egkcluster/smart-maintenance-release.json`.

Passaram 42 testes locais de manutenção e monitores, os simuladores `simulate_cluster.py` e `simulate_bot_interno.py`, e probes de versão isoladas nas imagens atuais dos seis hosts. A regressão progressiva impede uma segunda ação quando o alvo ou outro source está otimista. A ponte do cluster foi configurada explicitamente no perfil interno e bloqueada no perfil Lead.

Pendências observadas: Nethermind `1.39.3 → 2.1.0` exige revisão antes de atualizar o par de clientes; o worktree eth-docker do minipcamd3 está alterado e é pulado; código eth-docker e pacote/stack Hyperdrive seguem fora da receita comum. O cloudvero já tem indicação de reboot necessário; a rotina registra um pedido humano quando chegar a esse nó. Os serviços intencionalmente parados foram preservados.

Para interromper futuras atualizações: `sudo systemctl disable --now egkcluster-maintenance.timer`; isso não cancela uma ação já em andamento. Antes de parar uma service ativa, conferir `state/maintenance.json`, saúde e logs. Backups dos monitores e configuração ficam em `/opt/egkcluster/backup-monitors-*` e `backup-maintenance-*`; a rotina não faz downgrade automático dos clientes.

Fontes: [Eth Docker update](https://ethdocker.com/Support/Update), [Eth Docker GitHub](https://github.com/ethstaker/eth-docker), [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/), [DeepSeek thinking](https://api-docs.deepseek.com/guides/thinking_mode/), [NodeSet Hyperdrive update](https://docs.nodeset.io/node-operators/hyperdrive/updating).

## Piloto explícito Nethermind 1.39.3 → 2.1.0

`scripts/nethermind-pilot.py` executa uma única atualização autorizada. A receita aceita apenas um source Nethermind com mainnet padrão, nó `pre-prague-expiry`, banco Patricia existente, imagem binária oficial, tag atual `latest`, worktree limpo e os parâmetros extras de saúde/índice de logs revisados. Uma configuração diferente é recusada. A receita não altera `.env`: faz backup restrito e usa `--build-arg DOCKER_TAG=2.1.0@sha256:...` somente na construção de `execution`. Mantém uma tag da imagem anterior; não faz downgrade automático.

Antes de aplicar, valida o binário da imagem em container isolado, exige exatamente `2.1.0`, recoleta a saúde dos seis hosts e confirma que configuração, volumes e container vivo não mudaram. Aplica apenas `execution` com `--no-deps --no-build --pull never`. Nenhum `ethd update`, resync, limpeza, atualização de OS ou Git entra nesse piloto.

O piloto usa o mesmo `maintenance.lock` e estado durável do executor semanal. Uma interrupção deixa o ciclo bloqueado para reconciliação, e não repete a mutação. Exige cinco sources sincronizados e não otimistas, publicações novas dos dois VCs, avanço do head e três amostras adicionais de saúde, separadas por um minuto. O log da nova execução deve confirmar `State backend: patricia (existing patricia state detected)`; as famílias flat vazias criadas na sondagem 2.x não são tratadas como migração. As imagens de todos os outros clientes e o estado dos serviços intencionalmente parados devem permanecer iguais.

Instalar o script junto com os outros arquivos em `/opt/egkcluster/` e avaliar sem mutação:

```bash
python3 /opt/egkcluster/nethermind-pilot.py --config /opt/egkcluster/maintenance.json --node minipcamd
```

Para executar a autorização específica em serviço independente do terminal, no cloudvero:

```bash
sudo systemd-run --unit=egkcluster-nethermind-pilot --property=User=egk \
  --property=TimeoutStartSec=3h --property=Type=oneshot \
  python3 /opt/egkcluster/nethermind-pilot.py \
  --config /opt/egkcluster/maintenance.json --node minipcamd --run
```

O relatório é `/opt/egkcluster/state/nethermind-pilot-minipcamd.json`; consultar também `journalctl -u egkcluster-nethermind-pilot`. Um piloto concluído não autoriza genericamente outras mudanças de major, migrações Hyperdrive ou atualização do código eth-docker. A rotina comum deixa de bloquear este source quando observa Nethermind 2.1.0 em execução. O minipcamd3 mantém a trava de worktree alterado e requer tratamento separado.

Revisão de compatibilidade: [Nethermind 2.0.0, banco Patricia e configurações](https://github.com/NethermindEth/nethermind/releases/tag/2.0.0), [Nethermind 2.1.0](https://github.com/NethermindEth/nethermind/releases/tag/2.1.0), [seleção de backend na versão 2.1.0](https://github.com/NethermindEth/nethermind/blob/2.1.0/src/Nethermind/Nethermind.Init/FlatStateActivationPolicy.cs).

### Resultado observado em 3 de outubro de 2026 (UTC)

Piloto executado no cloudvero por `egkcluster-nethermind-pilot.service`, código `1effd24`, hash do script instalado `01082aadbe2628b2b1da29ed92f28a45bf03f521d4759157202d2c4b98564c8c`. O serviço terminou com `ExecMainStatus=0`; relatório `complete` em **03:52:04 UTC** e estado compartilhado `pilot_complete`, liberando o executor semanal. A próxima janela permaneceu 4 de outubro, 12:15 UTC.

No **minipcamd**, Nethermind passou de `1.39.3` para `2.1.0+b3e7e84c`, imagem local `sha256:e69e6af2d4d372f6a67ca041e94cc6502a02f02cc77cd54417cb07105c4bcf6b`. O container novo iniciou às 03:43:27 UTC e o log confirmou `State backend: patricia (existing patricia state detected)`. Os blocos avançaram imediatamente. `.env` permaneceu com o mesmo hash, e o mesmo volume/banco foi reutilizado; não houve resync nem alteração de pins, chaves ou parâmetros dos validadores.

Passaram a pós-checagem e três amostras adicionais: **cinco sources com `is_syncing=false`, `is_optimistic=false`, `el_offline=false` e distância zero**. As imagens dos outros clientes e o estado dos serviços intencionalmente parados permaneceram iguais. As publicações observadas no relatório final foram Vero às **03:48:27 UTC** e Hyperdrive VC às **03:49:51 UTC**, ambas posteriores à aplicação. Os avisos GestãoBot “Piloto Nethermind iniciando” (registro 11) e “Piloto Nethermind concluído” (registro 12) receberam recibos Meta **`delivered`**, o segundo às 03:52:08 UTC.

A checagem real da rotina semanal comparou o minipcamd com a release oficial `2.1.0`: `status=current`, lista de bloqueios de clientes vazia e ações comuns de clientes/OS elegíveis. Prysm continua `7.1.8`, com `7.2.0` disponível para a rotina normal. O minipcamd3 continua `1.39.3`, bloqueado por mudança de major e pelo conflito `UD .eth/ethdo/create-withdrawal-change.sh`, preservado. Hyperdrive e código eth-docker continuam fora desta receita. Passaram **51 testes locais**, incluindo nove cenários de piloto, além da revisão de whitespace e da verificação do hash do runtime.
