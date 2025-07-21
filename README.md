# Ethereum Validators Manager

Este projeto fornece uma ferramenta CLI em Python para gerenciar, atualizar e monitorar um cluster de validadores Ethereum Mainnet rodando em Ubuntu Server 24.04+ com ETH-DOCKER.

## Funcionalidades

- Listar status dos nós e clientes de execução/consenso.
- Automatizar upgrades de clientes via Docker.
- Monitorar o desempenho dos validadores com diagnóstico de conectividade multi-cliente (Lighthouse, Teku).
- Integrar gerenciamento via Tailscale domains.

## Pré-requisitos

- Python 3.10+
- Docker Engine & Docker Compose
- Acesso SSH aos nós (via Tailscale)

## Instalação

```bash
pip install -r requirements.txt
```

## Uso

```bash
# List nodes
python -m eth_validators.cli list
# Show status of one node
python -m eth_validators.cli status <name|tailscale_domain>
# Show all service images for one node
python -m eth_validators.cli status <name|tailscale_domain> --images
# Show client versions for a node
python -m eth_validators.cli versions <name|tailscale_domain>
# Show client versions for all nodes
python -m eth_validators.cli versions-all
# Show status and image versions for all nodes
python -m eth_validators.cli status-all
# Upgrade one node
python -m eth_validators.cli upgrade <name|tailscale_domain>
# Upgrade all nodes
python -m eth_validators.cli upgrade-all
# Monitor validator performance across all nodes
python -m eth_validators performance
```

## Monitoramento de Desempenho

O comando `performance` oferece uma visão diagnóstica da saúde dos seus validadores. Para cada nó definido no `config.yaml`, ele:

1.  Seleciona aleatoriamente um dos validadores associados ao nó (mapeado em `validators vs hardware.csv`).
2.  Verifica o status oficial do validador na beacon chain (`active_ongoing`, `exited`, etc.).
3.  Se o validador estiver ativo, tenta buscar métricas de desempenho detalhadas.
4.  Utiliza uma **estratégia de failover multi-cliente**: primeiro consulta os nós Lighthouse e, se não obtiver dados, tenta os nós Teku.
5.  Exibe uma tabela com os resultados, destacando problemas com cores:
    - **Amarelo**: Alertas, como `misses > 0`.
    - **Vermelho**: Status críticos, como `exited` ou `active_exiting`.

### Entendendo o Output

- **`Attester Eff.`**: Eficácia do atestador.
- **`Misses`**: Atestados perdidos.
- **`Inclusion Dist.`**: Distância de inclusão média.
- **`Status`**:
    - `active_ongoing`: Validador ativo e operando.
    - `active_ongoing (No Perf Data)`: O validador está ativo na rede, mas nenhum dos nós de consulta (`Lighthouse`, `Teku`) conseguiu obter suas métricas de desempenho. Isso indica um **problema de peering/conectividade** entre o nó do validador e os nós de consulta.
    - `Check CSV mapping`: O nó existe no `config.yaml`, mas não foi encontrado um validador correspondente no `validators vs hardware.csv`.

<!-- Example output for versions-all -->
```markdown
| Node      | Execution                             | Consensus   | MEV Boost      |
|-----------|---------------------------------------|-------------|----------------|
| minipcamd | Nimbus beacon node v25.7.0-94fb81-stateofus | Vero v1.1.3 | mev-boost v1.9.0 |
| minipcamd2 | Lighthouse v7.1.0-cfb1f73            | Vero v1.1.3 | mev-boost v1.9.0 |
| minipcamd3 | Teku v25.6.0                         | Besu v25.7.0| mev-boost v1.9.0 |
| laptop    | Grandine 1.1.1-f0e281a               | Nethermind v1.31.11 | mev-boost v1.9.0 |
```  

## Configuração

Edite `eth_validators/config.yaml` e `eth_validators/validators vs hardware.csv` para definir seus nós, credenciais, stacks e o mapeamento de validadores.
