# Manutenção semanal do egkcluster

O executor roda sozinho por `egkcluster-maintenance.timer` no **cloudvero**, domingo às 09:15 em `America/Sao_Paulo`. Ele não depende de uma sessão de terminal, de um modelo local, nem de cron no minipcamd4. Esse servidor saiu do cluster Ethereum e não está na configuração.

## Escopo e ativação

Copiar `scripts/cluster-maintenance.py`, `scripts/eth_docker_source.py`, `scripts/gestaobot_client.py`, `scripts/hyperdrive_vc.py` e `config/maintenance.example.json` para `/opt/egkcluster/`, deixando o JSON como `/opt/egkcluster/maintenance.json`. A service usa `User=egk`, portanto `egk` precisa de leitura/escrita de `/opt/egkcluster/state`, da própria configuração, de sua chave SSH para os cinco nós e de `sudo -n docker` e `sudo -n apt-get` no cloudvero. A chave DeepSeek fica em `/opt/egkcluster/maintenance.env`, arquivo separado com permissão restrita (`0600`), na forma `DEEPSEEK_API_KEY=...`. Não copiar nem ler `.env.interno` do GestãoBot. O cliente do bot usa apenas a API local `http://127.0.0.1:8101` e valida essa origem.

O exemplo vem com `enabled: false` e `clients: false`, `os: false` em todos os seis hosts. Habilitar explicitamente a chave geral e cada ação por nó após revisão dos caminhos reais, acesso SSH, sudo e estado de saúde. Portas SSH 2222 valem do cloudvero; a porta 22 é aceita apenas como substituição de teste da estação. Instalar service e timer **apenas** depois da revisão e autorização de publicação. `Persistent=true` executa um horário perdido quando o timer é ativado novamente, sujeito às mesmas travas de estado.

Comandos de avaliação local:

```bash
python3 scripts/cluster-maintenance.py --config config/maintenance.example.json --check
python3 scripts/cluster-maintenance.py --config config/maintenance.example.json --dry-run
python3 -m unittest discover -s tests -p test_maintenance.py
```

`--check` e `--dry-run` fazem somente SSH local/consulta HTTP e leitura de releases GitHub. Não enviam WhatsApp, não chamam DeepSeek, não fazem `apt-get update`, nem atualizam clientes. `--refresh-approvals` consulta o estado de códigos existentes no GestãoBot e persiste a resposta local, sem mandar aviso ou executar reboot. `--run` é a única rota que atualiza nós. O arquivo JSON pode continuar desabilitado para produzir inventário de avaliação. Um erro de SSH, GitHub (inclusive rate limit), LLM, quorum ou comunicação GestãoBot interrompe o ciclo. O aceite do endpoint do GestãoBot prova apenas que a API aceitou o pedido; a entrega do WhatsApp depende dos recibos Meta.

## Decisão por nó

O executor coleta os cinco pares EL/CL e os validadores do cloudvero, que não roda beacon ou EL locais. Cada probe registra montagem do data-root, espaço livre, percentual usado, beacon sync/EL offline dos cinco sources, estado e imagem/ID dos containers, versões dos binários em execução (sem chamar `ethd version`), commit, pins conhecidos, pacotes apt pendentes e arquivo de reboot. Ele consulta releases oficiais de eth-docker, Geth, Nethermind, Prysm, Lighthouse, Lodestar, Nimbus, Vero e Hyperdrive pela API GitHub, incluindo a tag e um trecho de notas de cada release. Extrai as versões em execução de EL/CL/Vero e compara com as tags oficiais. Se a versão instalada ou release for desconhecida, diferir em major ou estiver à frente da release consultada, pula a ação de **clientes** nesse nó e registra revisão pendente; uma ação de OS habilitada ainda pode ocorrer com todos os gates de saúde. Por exemplo, Nethermind 1.39.3 → 2.1.0 fica fora da atualização automática. Tags mutáveis e pins não garantem a nova versão, portanto o relatório pós-ação compara as versões observadas e não afirma que tudo está atualizado apenas pelo sucesso do comando. O Hyperdrive é comparado separadamente: CLI (`hyperdrive --version`), pacote apt, imagens dos dois daemons e binário Lodestar VC. Versões atuais não geram uma pendência genérica. Uma diferença em CLI/pacote/daemons continua exigindo revisão de migração; o Lodestar VC do mesmo major tem a receita restrita descrita abaixo.

A saúde deve estar completa **antes de cada ação e novamente após o build, imediatamente antes da aplicação**: seis probes presentes; cada data-root com pelo menos 10 GiB livres e uso abaixo de 80%; nos cinco sources, CL não sincronizando nem otimístico, `el_offline=false` e containers EL/CL em pé; no cloudvero, Vero, web3signer e os containers Hyperdrive configurados em pé, além de publicações de Vero e `hyperdrive_sw_vc` nos últimos 15 minutos. A janela cobre o intervalo possível entre duties de épocas consecutivas. A pós-checagem exige novas publicações dos dois VCs **após o comando de atualização terminar** e após o `StartedAt` atual de cada container; mensagens antigas não liberam o próximo nó. Todos os cinco sources devem estar synced e não otimísticos antes de qualquer ação seguinte, com pelo menos dois **outros** pares EL/CL saudáveis. A análise DeepSeek Flash envia somente inventário/resumo JSON, devolve `veto`, `summary`, `reason` em português brasileiro conciso, e nunca fornece comandos ao executor. Notas de release entram como dados sem confiança e não viram instruções. O JSON é validado estritamente e há uma tentativa adicional após resposta malformada. Um veto ou falha interrompe a execução com alerta.

Para cada nó habilitado, na ordem do JSON, o executor faz:

1. Backup datado de `.env` e guarda estado `mutating` em disco antes do primeiro comando.
2. Para clientes: `docker compose ... pull --ignore-buildable`, depois `docker compose ... build --pull` (`--no-cache` quando algum `*_DOCKERFILE` conhecido é `Dockerfile.source`). **Antes** de subir a stack, executa apenas os binários `--version` das imagens locais recém-construídas em containers descartáveis, sem rede, volumes da stack ou ambiente da stack, e compara o major instalado e a release esperada. Declarações `VOLUME` da própria imagem são substituídas por tmpfs efêmeros, sem montar dados do host. Major novo, versão desconhecida ou divergência da release sem pin fixo bloqueiam a aplicação. Um pin fixo permite versão antiga do mesmo major, que continua visível como gap. Confere novamente os IDs das tags locais e só então usa `docker compose ... up -d --no-build --pull never`; `ethd up` simples passaria `--remove-orphans` e poderia remover containers parados. `--ignore-buildable` evita tentar baixar tags locais como `geth:local` de um registry. Esse caminho mantém pins existentes e atualiza imagens para a definição atual do compose. Um build de código fonte com target Git fixo permanece nesse target. Não edita fee recipient, chaves, threshold ou fallback.
3. Para OS nos cinco sources: `apt-get update` e `DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get --no-remove upgrade`, com timeout de lock. No cloudvero, após `apt-get update`, lê a lista de pacotes atualizáveis, remove Hyperdrive da seleção, simula a transação para bloquear qualquer atualização transitiva de Hyperdrive ou remoção, e aplica somente a lista restante via `apt-get --only-upgrade --no-remove install`. Lista vazia encerra sem instalar. O pacote Hyperdrive fica como pendência separada porque seu `postinst` pode ligar o operator intencionalmente parado. Não executa `autoremove`, `dist-upgrade`, `full-upgrade` nem reboot.
4. Recoleta todos os nós e aguarda o nó alterado voltar a synced, não otimístico, EL online, disco dentro do limite, containers ativos e Vero publicando atestação. Interrompe sem passar ao próximo quando qualquer outro nó perde saúde/quorum ou quando o timeout acaba.

`./ethd update --non-interactive` **não é usado**: a versão local declara que o modo não interativo assume sim para resync/migrações e seu `update` chama `docker system prune --force`. Isso poderia apagar containers intencionalmente parados. A atualização do código eth-docker usa uma receita separada no mesmo ciclo quando `source=true` e `clients=true`; sem esse flag, atualiza imagens a partir da definição já instalada. Esquemas novos fora da receita permanecem pendentes de revisão. A receita `hyperdrive=true`, somente no cloudvero, atualiza o Lodestar VC conforme descrito abaixo; CLI/pacote e os demais serviços Hyperdrive ficam sujeitos à revisão quando houver versão diferente. `hyperdrive_sw_operator` e eth-lido permanecem parados por decisão operacional.

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


## Atualização progressiva do código Eth Docker

`scripts/eth_docker_source.py` prepara um merge da revisão oficial em worktree isolado, preservando o histórico e os commits locais. Antes de modificar o checkout vivo, guarda `.env` e um Git bundle em diretório privado `eth-docker-local-backups/source-*`. Conflitos no preview não alteram código ou configuração em uso. A opção Python `prepare(..., apply=False)` realiza apenas a preparação e comparação. O caminho de aplicação usa fast-forward para o merge validado e troca atômica de `.env`, modo `0600`, preservando o proprietário original.

A receita reconhece esquemas `.env` 67 a 72 em mainnet: conserva todos os valores e pins existentes, acrescenta somente os defaults ausentes, atualiza `ENV_VERSION` e preserva a semântica antiga de `EPBS_BUILD_FACTOR=100` como `always` na passagem para 72. O sentinel `/dev/null` de `NODE_EXPORTER_COLLECTOR_MOUNT_PATH` vira vazio, conforme a migração upstream. FlatDB explícito, profiles de ferramentas, nomes Compose fora da receita, mudança em volumes, portas, redes, imagens ou parâmetros protegidos de EL/CL/VC/signer/PostgreSQL exigem revisão. Dumps completos do Compose ficam privados; o estado registra hashes e nomes das variáveis, sem seus valores.

`source=true` em cada nó habilita essa preparação antes do build de clientes. A revisão vem de `eth_docker_revision` (SHA de 40 caracteres, para piloto revisado) ou do `main` oficial a cada ciclo. Um esquema upstream fora da faixa suportada conserva o código instalado e registra a pendência; as demais ações comuns continuam sujeitas aos gates. O preview e a comparação de Compose precisam passar em cada máquina. Seleciona apenas serviços já em execução, deixando web3signer e PostgreSQL com seus containers e binários atuais. Uma dependência nova `prom-init` pode preparar permissões do volume de métricas; não atua nos dados Ethereum ou de assinatura. Depois do build e da prova de versão isolada, coleta novamente a saúde de todos os hosts e aplica somente essa seleção, com `--no-deps --no-build --pull never --force-recreate`. Não ativa containers parados nem ferramentas de chaves.

A aplicação de cada host precisa concluir a pós-checagem: cinco sources sincronizados, não otimistas, EL online e publicações dos dois validadores posteriores ao término da aplicação. O código Hyperdrive continua fora desta receita. Esquemas desconhecidos e mudanças de major não são liberados por esta autorização.

### Minipcamd3: Nethermind concluído

O conflito `UD .eth/ethdo/create-withdrawal-change.sh` era um estado de índice remanescente: o helper vivo era idêntico ao blob de `HEAD`. Em 3 de outubro, foi preservado junto com o índice e seus blobs em `/home/egk/eth-docker-local-backups/minipcamd3-conflict-20261003T041209Z`, no próprio minipcamd3. A restauração desse único caminho ao `HEAD` limpou o índice sem alterar os bytes do arquivo. O helper não foi executado.

`egkcluster-nethermind-minipcamd3-pilot.service` terminou com código 0 e relatório `complete` em **04:22:22 UTC**. Nethermind passou de `1.39.3` a `2.1.0`, preservando Patricia e o hash de `.env` `2f5e9635a281ef6cc3a36c8e31249054a6cf5c6a6dbf7a0b3d571e3960f55ff4`. Passaram a pós-checagem e três observações adicionais; todos os sources tinham distância zero e flags de sync/optimistic/EL offline falsas. Os avisos GestãoBot 13 e 14 receberam `delivered`, a conclusão em **04:22:26 UTC**. As pendências históricas de major e índice desse nó foram resolvidas.

### Saída curta da API DeepSeek

O primeiro preflight Eth Docker, às 04:51:45 UTC, terminou sem mutação porque o Flash atingiu o teto de 4096 tokens no modo thinking. A revisão periódica agora solicita explicitamente `thinking.type=disabled` e `reasoning_effort=none`, mantendo o mesmo modelo, teto de saída, esquema JSON e recusa de `finish_reason=length`. O modelo continua analisando inventário e avisos de release; as travas de execução são determinísticas. O parâmetro segue a [documentação oficial DeepSeek](https://api-docs.deepseek.com/api/create-chat-completion/), que habilita thinking por padrão e permite desabilitá-lo. Isso evita consumir o teto com raciocínio separado antes de produzir o breve JSON exigido.


### Probes sem efeitos colaterais

No primeiro build preparado do minipcamd3, a comparação pré-aplicação detectou uma reescrita de `DOCKER_ROOT_MOUNTPOINT` feita pela inicialização do próprio `ethd cmd`. O estado ficou `blocked` antes de qualquer `up`, com os containers Ethereum originais ainda em execução. O código agora usa Docker Compose diretamente, com diretório, `.env`, project name e seleção de arquivos/serviços explícitos. As probes leem o banner público do README e chamam somente os binários `--version` dos containers ativos; nem `ethd version` é invocado, pois ele também executa essa inicialização e pode ajustar arquivos e permissões.

A comparação de hash e a trava de retomada permanecem. Antes de retomar o piloto, a reconciliação precisa provar que apenas o campo de métricas foi reescrito, os IDs dos containers Ethereum são os mesmos do inventário anterior e os demais parâmetros são idênticos ao preview validado. Conserva-se o arquivo reescrito em backup privado e restaura-se apenas o `.env` do preview, com proprietário original e modo `0600`. Não se apaga estado desconhecido para repetir a ação.


### Piloto Eth Docker concluído no minipcamd3

O piloto serial em `egkcluster-eth-docker-pilot.service`, executado por `User=egk` no cloudvero e com a chave apenas no `EnvironmentFile`, terminou com código 0 às **05:09:59 UTC**, em 3 de outubro de 2026. O estado geral é `partial` porque o relatório conserva a pendência Hyperdrive; a única ação planejada foi concluída, sem erro ou ação pulada. A prova foi preservada em `/opt/egkcluster/state/maintenance-eth-docker-minipcamd3-complete-20261003.json`.

O checkout do minipcamd3 passou a `5d2add7574bcbe2f374311620d4da497cc8c32d6`, `main` oficial revisado. O schema ficou 72; `.env` mantém o hash validado `adb9a98afe98da3575669b75fd7166170d407b404cd98fe94ff7093f720e4d7e`, proprietário `egk` e modo `0600`. A reconciliação documentada do campo de métricas está em `/opt/egkcluster/state/reconciliation-ethd-telemetry-minipcamd3-20261003.json`, sem perda do estado bloqueado anterior.

Nethermind permaneceu `2.1.0` e Lodestar passou de `1.48.0` a `1.49.0`, ambos `current` frente às releases consultadas. As imagens aplicadas foram respectivamente `sha256:2f2622927e0766b5569732abe40ede1641ed48ce136a13259ca5aa43367d9f28` e `sha256:c157a150def314dbe8688e244aa5fb94dee73b8d2cd045a85fd51daee7d690d4`. Os containers iniciaram às 05:08:13 e 05:08:12 UTC; o Nethermind registrou `State backend: patricia (existing patricia state detected)` às 05:08:16. O beacon retornou distância zero, não sincronizando, não otimista e EL online. A pós-checagem confirmou publicações de Vero às **05:08:39 UTC** e Hyperdrive VC às **05:09:51 UTC**, após a aplicação. O resumo GestãoBot (registro 20) recebeu `delivered` às 05:10:02 UTC.

O runtime usa o código `86123e0` e passou **66 testes locais**: inclui merges Git reais preservando commits locais, conflito sem alteração do checkout vivo, proteção de configuração/volumes, imagem/major antes de aplicar, ausência de mutação por probes e trava progressiva contra sync/optimistic em qualquer outro source. Os hashes instalados constam de `smart-maintenance-release.json`.


### Conferência das imagens realmente em execução

A auditoria posterior à primeira rodada encontrou os novos binários construídos, mas quatro hosts ainda executavam containers das imagens anteriores. A checagem antiga comparava apenas major após o retorno do script. O auxiliar `prom-init` mantinha stdin aberto por padrão e consumia as linhas seguintes do transporte SSH, incluindo `up`. Essa rodada confirmou a atualização de código/configuração, mas não a troca efetiva desses oito containers; o relatório original foi preservado.

O executor agora recria explicitamente os serviços selecionados. Imediatamente após o comando, compara o `Image` de cada container EL/CL/Vero com o ID da candidata validada. A pós-checagem também exige igualdade da versão em execução e do ID, além da saúde e das atestações novas. Um comando com sucesso que conserve imagem antiga bloqueia a sequência. O teste de regressão simula esse caso e prova que nenhum segundo nó é iniciado.

### Revisões de release com escopo definido

A revisão DeepSeek recebe rede, arquivos Compose e tipos EL/CL selecionados, além do hash da configuração. `RELEASE_REVIEWS` documenta somente transições exatas já revistas nas fontes oficiais. Essas notas são enviadas apenas quando as versões e a configuração em uso correspondem ao escopo; outras versões, rede diferente, cliente validador e Nimbus em modo arquivo não herdam a revisão. Nenhum desses registros altera `veto`: um veto da API continua interrompendo antes de qualquer ação.

Para a rodada de 3 de outubro, Nethermind já estava em 2.1.0; os avisos de flat/PoA relativos à passagem de 1.x não representam essa reconstrução da mesma versão. Geth 1.17.5 → 1.17.7 conserva banco e política de histórico e não executa o comando opcional `prune-history`. Lodestar 1.49 trata deduplicação de payloads Gloas, cuja ativação citada é Sepolia. Prysm roda como beacon apenas, sem mudar proposer settings dos validadores. Lighthouse 8.2.3 é a manutenção de segurança de 8.2.2, reutilizando o banco. O OrangePi tem `CL_NODE_TYPE=pruned`; a alteração de Nimbus 26.9 no modo `archive` não se aplica a esse modo.

Fontes da revisão: [Geth 1.17.6](https://github.com/ethereum/go-ethereum/releases/tag/v1.17.6), [Geth 1.17.7](https://github.com/ethereum/go-ethereum/releases/tag/v1.17.7), [Prysm 7.2.0](https://github.com/OffchainLabs/prysm/releases/tag/v7.2.0), [Lighthouse 8.2.3](https://github.com/sigp/lighthouse/releases/tag/v8.2.3), [Lodestar 1.49.0](https://github.com/ChainSafe/lodestar/releases/tag/v1.49.0), [Nimbus 26.9.0](https://github.com/status-im/nimbus-eth2/releases/tag/v26.9.0) e [Nimbus 26.9.1](https://github.com/status-im/nimbus-eth2/releases/tag/v26.9.1).


O transporte remoto passou a ler todo o script antes de iniciar Bash, deixando stdin dos comandos em `/dev/null`. O auxiliar também usa `--interactive=false --no-tty` e redirecionamento explícito de entrada. Um teste executa um processo que lê stdin até EOF e prova que o comando posterior ainda é executado. A documentação de [Docker Compose run](https://docs.docker.com/reference/cli/docker/compose/run/) confirma que stdin interativo permanece aberto por padrão.

A tentativa com a conferência estrita detectou os binários antigos no primeiro nó e terminou `blocked` às **06:20:32 UTC**, sem concluir nenhuma ação ou iniciar o segundo nó. A reconciliação em `/opt/egkcluster/state/reconciliation-helper-stdin-20261003.json` confirmou as mesmas imagens EL/CL/VC em todos os hosts, hashes de configuração/HEAD preservados e todos os gates de saúde. O estado bloqueado original foi arquivado antes da retomada. O ajuste de transporte está no commit `357c4a6`, runtime SHA-256 `c509fd557d601ca37f70b024bd5f113b977ec573bc882d8ad4efb588db49cf64`, com **74 testes** aprovados.


### Resultado final da rodada Eth Docker

A preparação de código/configuração terminou em todos os seis hosts às **05:37:53 UTC**, em 3 de outubro de 2026, mantendo os commits locais e incluindo o upstream oficial `5d2add7574bcbe2f374311620d4da497cc8c32d6`. A correção das imagens realmente em execução terminou às **06:47:28 UTC** por `egkcluster-effective-client-images.service`, no cloudvero. A service retornou código 0, sem ações puladas ou erro. Os quatro nós foram concluídos em ordem: minipcamd **06:31:49**, minipcamd2 **06:35:54**, minitx **06:42:52**, OrangePi **06:47:28**, todos UTC. Cada avanço exigiu os cinco sources saudáveis, versões/IDs aplicados e publicações posteriores dos dois VCs.

A auditoria independente de **06:51:07 UTC** consultou novamente as releases e confirmou os binários e imagens dos containers em execução:

| Host | EL | CL / VC | HEAD Eth Docker |
| --- | --- | --- | --- |
| minipcamd | nethermind 2.1.0 | prysm 7.2.0 | `0fabdfcb2c4c` |
| minipcamd2 | geth 1.17.7 | lighthouse 8.2.3 | `8392681d7cfa` |
| minipcamd3 | nethermind 2.1.0 | lodestar 1.49.0 | `5d2add7574bc` |
| minitx | geth 1.17.7 | lodestar 1.49.0 | `5d2add7574bc` |
| orangepi5-plus | geth 1.17.7 | nimbus 26.9.1 | `5d2add7574bc` |
| cloudvero | — | vero 1.4.1 | `562a49abec1d` |

Os cinco pares EL/CL estavam com `is_syncing=false`, `is_optimistic=false` e `el_offline=false`; Vero e Hyperdrive VC tinham publicações novas. A distância pode variar em um slot durante a coleta: o gate usa as flags reais do beacon. Todos os checkouts estavam limpos e incluíam o upstream revisado. Os hashes de `.env` coincidiram com a migração validada, schema 72, proprietário original `egk` e modo `0600`.

Os **11 containers protegidos** do cloudvero conservaram exatamente ID, imagem, estado e `StartedAt` da captura anterior: stack Hyperdrive, eth-lido, web3signer e PostgreSQL. Os serviços intencionalmente parados continuaram parados. Nenhum reboot ou comando de resync foi executado. Os hashes dos seis arquivos de runtime coincidiram com `smart-maintenance-release.json`. O código de execução é `357c4a6`, worker SHA-256 `c509fd557d601ca37f70b024bd5f113b977ec573bc882d8ad4efb588db49cf64` e módulo de source SHA-256 `d7793501f7dfd14789e6a848297b499968a24ec02bad9d75ff9e4e3e368394ed`; **74 testes** passaram.

O início da retomada (GestãoBot 29) recebeu `delivered` às 06:23:32; o resumo final (31) recebeu `delivered` às **06:47:32 UTC**. O estado é `partial` porque conserva as pendências de Hyperdrive e reboot humano do cloudvero. O pedido antigo de reboot, registro 23/código 742082, está **expirado**; aprovação não executa reboot automaticamente.

As provas privadas estão no cloudvero: `state/maintenance-effective-client-images-complete-20261003.json`, `state/ethereum-maintenance-final-audit-20261003.json` e `state/maintenance-effective-image-checkpoints-20261003.jsonl`, sob `/opt/egkcluster/`. Uma cópia local está em `/home/egk/ethereum-maintenance-reports-20261003/`, modo restrito. Os estados das tentativas interrompidas permanecem arquivados, incluindo a reconciliação do transporte SSH.

Os três timers permanecem ativos e habilitados. A rotina comum tem `clients=true`, `source=true` e `os=true` nos seis hosts, usando a API DeepSeek Flash e o GestãoBot local. A próxima janela é **4 de outubro de 2026, 12:15 UTC / 09:15 São Paulo**, com o mesmo lock, regras de versão, preservação de dados e gates progressivos. O minipcamd4 continua fora do cluster Ethereum.

## Receita restrita de Hyperdrive Lodestar VC

Com `nodes.cloudvero.hyperdrive=true`, a rotina semanal atualiza apenas `sw_vc` quando seu Lodestar está atrás da release oficial, no mesmo major, e CLI/pacote/daemons Hyperdrive já coincidem com a release oficial. CLI usa `--version`; o comando `hyperdrive version` não existe. O pacote continua excluído do apt automático. Não usar `hyperdrive service status`, `config`, `compose` ou `start` como probes: o CLI pode regenerar os templates e o `start` sobe também o operator.

A receita compara as oito definições Compose existentes com o container vivo: origem do projeto, comando, entrypoint, usuário, ambiente configurado e os dois bind mounts, incluindo `/validators`. Faz backup privado da configuração e mantém uma tag da imagem anterior. Puxa apenas `chainsafe/lodestar:latest`, verifica a versão por um container isolado sem rede ou dados de assinatura, recoleta a saúde completa, confere novamente configuração/IDs e recria somente `sw_vc` com `--no-deps --no-build --pull never --force-recreate`. Confirma imediatamente versão e imagem; a pós-checagem exige atestações novas dos dois VCs. Mantém o mesmo diretório de proteção contra slashing e a mesma implementação de VC.

O piloto autorizado 1.48.0 → 1.49.0 roda por `hyperdrive-pilot.py`, sob o `maintenance.lock`, via serviço systemd no cloudvero com a chave somente no `EnvironmentFile`. Além da pós-checagem, observa duas amostras adicionais separadas por um minuto e conserva a identidade dos containers Ethereum e de assinatura não selecionados. O relatório privado é `state/hyperdrive-pilot-20261003.json`. Os novos gates passam por testes de mounts, ambiente, versão principal, tag mutável, estado do operator e perda de saúde após o pull.

A [release Lodestar 1.49.0](https://github.com/ChainSafe/lodestar/releases/tag/v1.49.0) inclui correções no processo de assinatura e proteção contra slashing e é recomendada pelo upstream para mainnet. Esta operação usa os dados existentes; nenhuma importação, troca de implementação ou alteração de parâmetros de assinatura faz parte da receita.

## Reboot individual autorizado do cloudvero

O executor semanal continua sem executar reboot. Para esta pendência individual, `approved-reboot.py` prepara uma ação concreta e abre **um novo código** no GestãoBot. O código expirado fica em `superseded_reboot_requests`, sem virar aprovação ou conclusão. O serviço de espera `egkcluster-cloudvero-reboot-waiter` consulta o código e só agenda um reboot se o bot responder `aprovada`, a saúde completa passar novamente e os containers/configuração coincidirem com a preparação. A aprovação por WhatsApp desse pedido individual permite a execução anunciada no próprio pedido. Rejeição ou expiração não executa a operação.

A preparação altera apenas a política de reinício do `hyperdrive_sw_operator` parado para `restart=no`, conservando a política anterior no relatório; assim Docker não o liga na inicialização. O serviço persistente `egkcluster-reboot-recovery.service` deve estar habilitado antes de agendar o reboot. Após iniciar, ele apenas verifica recuperação, nunca repete a reinicialização: exige mudança de boot ID, ausência de `reboot-required`, mesmas imagens/IDs e estado ativo/parado dos containers Ethereum, mesmo contexto de assinatura, cinco sources saudáveis, novas publicações dos dois VCs após o seu `StartedAt`, serviços/timers e `/health` HTTP 200 em 8091 e 8101. Conclui o código no GestãoBot e move a pendência para o histórico somente depois dessas provas. O recovery é desabilitado após concluir.

O relatório privado é `state/cloudvero-approved-reboot-20261003.json`. A preparação, espera e recuperação usam o mesmo `maintenance.lock`. Antes de agendar, o journal e o estado compartilhado são gravados atomicamente; uma interrupção conserva a fase para reconciliação. Os testes cobrem expiração, perda de saúde com aprovação, gravação antes da execução, prevenção de reboot repetido e preservação de containers parados/imagens.

## Hyperdrive aplicado em 3 de outubro de 2026 (UTC)

O piloto independente `egkcluster-hyperdrive-pilot.service` terminou com `ExecMainStatus=0` e relatório `complete` às **13:14:12 UTC**. CLI, pacote e os dois daemons Hyperdrive já estavam na release `1.3.0`; a pendência efetiva era seu Lodestar VC. Foi aplicada apenas a atualização **1.48.0 → 1.49.0** no `hyperdrive_sw_vc`, imagem `sha256:c13eac6aada7fe3adbc6232ad72726081746bfea4c27563a637977066f835a23`, container `bdf7db678261`, iniciado às **13:09:13 UTC**.

O hash de `user-settings.yml` permaneceu `dbe663567a67b5aa5a56f89096f1807d689c308db2afc025428d724353d2da1b`; comando, ambiente configurado e mounts existentes foram preservados. Os **12 containers Ethereum/assinatura não selecionados** mantiveram identidade, imagem, estado e horário de início. Passaram a pós-checagem e duas observações adicionais: cinco sources com `is_syncing=false`, `is_optimistic=false`, `el_offline=false`; publicações novas de Vero e Hyperdrive VC após a aplicação. A análise pela API DeepSeek Flash retornou `veto=false`.

O aviso de início (GestãoBot 39) recebeu `delivered` às **13:05:41 UTC**; o de conclusão (40), às **13:14:16 UTC**. A primeira tentativa foi bloqueada antes de aplicar por reinício de um container Immich, fora do cluster. A reconciliação verificou Lodestar 1.48.0 e todas as identidades/configurações Ethereum inalteradas antes de retomar. O registro permanece em `state/reconciliation-hyperdrive-preapply-20261003.json` e o relatório da tentativa em `state/hyperdrive-pilot-blocked-before-apply-20261003.json`; o gate passou a proteger os containers Ethereum e de assinatura.

O código instalado é `9a2891b`, com **91 testes**; worker SHA-256 `f87d48ed4813a77e3897f7796233458753b7c005571421dfe7491815df3adf93`, módulo Hyperdrive `6cf023651898f46c6495011272d2cf6693a98edf8a238cdc862e7ae7f7cc6c18` e executor de reboot `b5dbdc26116baa63354600e960db5e76d930c7c4d3b71d3ecb7b151b647fc19c`. A configuração em produção tem `cloudvero.hyperdrive=true`; os três timers continuam ativos e a próxima manutenção semanal é **4 de outubro às 12:15 UTC**.

A preparação do reboot validou também os serviços Integra, `/health` HTTP 200 em 8091 e 8101 e o recovery persistente habilitado. O `hyperdrive_sw_operator` continuou parado e passou a `restart=no`; eth-lido validator/signer continuam parados. O pedido antigo expirado foi preservado em `superseded_reboot_requests`. O novo pedido (GestãoBot 41) recebeu `delivered` às **13:15:58 UTC**; o waiter independente só executa após aprovação válida. No fechamento do piloto, o único pendente era o reboot: `gaps_summary={}` e versões Hyperdrive verificadas `current`. A execução/recuperação do reboot deve ser provada separadamente pelo seu relatório, sem inferir execução a partir da entrega do pedido.

Provas privadas: `/opt/egkcluster/state/hyperdrive-pilot-20261003.json` e `cloudvero-approved-reboot-20261003.json`; cópias locais em `/home/egk/ethereum-maintenance-reports-20261003/`, com acesso restrito.

## Autorização explícita de reboot nesta sessão

Após a expiração do pedido WhatsApp, o usuário instruiu explicitamente **“Rebota o cloudvero”** nesta sessão. A operação individual usa `approved-reboot.py --execute-session --authorization-text 'Rebota o cloudvero'`. Essa rota aceita somente a instrução registrada e um pedido anterior expirado, sem execução, no mesmo boot; continua exigindo lock exclusivo, cinco sources sincronizados/não otimistas, ambos VCs atestando, quorum, serviços e recovery habilitados e os containers intencionalmente parados com `restart=no`.

O journal registra `authorization.channel=user-session` e o texto da instrução. O pedido expirado é arquivado, sem alterar a aprovação no banco do GestãoBot ou concluir seu código. Avisos de início e conclusão seguem pelo GestãoBot. A recuperação exige a mesma autorização no estado compartilhado e no journal, além de todos os gates de boot/saúde anteriores. O histórico diferencia essa autorização direta dos códigos aprovados pelo WhatsApp. A rotina semanal continua sem reinicialização automática. Passaram **94 testes**, incluindo autorização específica, preservação do pedido expirado e bloqueio por source otimista mesmo com autorização humana.

## Reboot concluído em 3 de outubro de 2026 (UTC)

O serviço independente `egkcluster-cloudvero-session-reboot` registrou a autorização humana às **14:59:28 UTC** e agendou o único reboot às **14:59:29 UTC**. Cloudvero voltou com **Linux `6.8.0-146-generic`**, substituindo `6.8.0-139-generic`. O boot ID mudou de `17f6f083-9051-447f-907b-0b342ad4458e` para `062fa0e0-f7b4-4ea4-bfd7-3fdb4dd72f0e`; `reboot-required` ficou ausente.

A recuperação persistente terminou com `ExecMainStatus=0` às **15:12:25 UTC**. Vero publicou após o boot às **15:12:14 UTC**, e Hyperdrive VC publicou desde **15:01:15 UTC**, com novas publicações até 15:11:39 na amostra final. Os erros de conexão Vero → web3signer ocorreram somente entre 15:00:34 e 15:00:44, durante a inicialização do assinador. Nenhum restart adicional foi necessário; a conclusão aguardou a próxima atestação efetiva do Vero.

Passaram todos os gates: cinco sources sincronizados e não otimistas, EL online, serviços Integra e timers ativos, `/health` HTTP 200 em 8091/8101, imagens/IDs/políticas e estados ativo/parado dos containers Ethereum preservados, contexto de assinatura e configuração Hyperdrive iguais, threshold Vero **2**, hashes de runtime conferidos. Operator e eth-lido validator/signer continuaram parados. O estado compartilhado passou para **`complete`**, `pending_reboots=[]` e `gaps_summary={}`; o reboot foi registrado com sua autorização de sessão no histórico. O recovery se desabilitou após concluir.

GestãoBot 42, início autorizado nesta sessão: `delivered` às **14:59:32 UTC**. GestãoBot 43, conclusão: `delivered` às **15:12:28 UTC**. A próxima manutenção semanal permanece **4 de outubro às 12:15 UTC** (09:15 São Paulo), independente do terminal e com DeepSeek por API.

Prova final privada: `/opt/egkcluster/state/cloudvero-reboot-final-audit-20261003.json`; cópia local `/home/egk/ethereum-maintenance-reports-20261003/reboot-final-audit.json`. O pedido expirado ficou em `state/cloudvero-reboot-request-expired-20261003.json`. Código de execução do reboot: `a371723`, com 94 testes; a documentação de resultado é publicada separadamente.
