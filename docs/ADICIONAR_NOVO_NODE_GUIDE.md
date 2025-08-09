# 🆕 Guia: Como Adicionar um Novo Node Interativamente

## Visão Geral

O novo comando `node add-node` oferece uma experiência interativa similar ao quickstart para adicionar novos nodes ao seu cluster Ethereum existente. É uma forma fácil e guiada de expandir sua infraestrutura de validadores.

## Como Usar

### Comando Básico
```bash
python3 -m eth_validators node add-node
```

### Processo Interativo

O wizard irá guiá-lo através de 6 etapas:

#### 🖥️ Etapa 1: Informações Básicas do Node
- **Nome do Node**: Escolha um nome único (ex: 'server2', 'validator-node-3')
- **Domínio Tailscale**: O endereço Tailscale do node (ex: 'mynode.tailnet.ts.net')
- **Usuário SSH**: Usuário para conexão SSH (padrão: 'root')

#### 🔗 Etapa 2: Teste de Conectividade
- Testa automaticamente a conexão SSH com o node
- Verifica se o node está acessível via Tailscale
- Permite continuar mesmo se a conexão falhar (para configuração offline)

#### 🔍 Etapa 3: Detecção Automática de Serviços
- **Detecção Automática**: Usa `docker ps` para identificar stacks rodando:
  - `eth-docker` (Ethereum clients padrão)
  - `obol`/`charon` (Distributed Validator Technology)
  - `rocketpool` (Rocket Pool)
  - `hyperdrive` (NodeSet Hyperdrive)
  - `ssv` (SSV Network)
  - `lido-csm` (Lido CSM)
  - `stakewise` (StakeWise)

- **Seleção Manual**: Se preferir, pode escolher manualmente os stacks

#### ⚙️ Etapa 4: Configuração Adicional
- **Ethereum Clients**: Escolhe se quer habilitar execution/consensus clients
- Detecta automaticamente se é um node validator-only (como Charon)

#### 📋 Etapa 5: Resumo da Configuração
- Mostra todas as configurações detectadas/escolhidas
- Permite confirmar ou cancelar antes de salvar

#### 💾 Etapa 6: Salvamento
- Adiciona o node ao arquivo `config.yaml` existente
- Preserva todas as configurações existentes
- Mostra próximos passos recomendados

## Exemplo de Uso Prático

### Cenário: Adicionando um Node Rocket Pool

```bash
$ python3 -m eth_validators node add-node

🚀 Welcome to the Interactive Node Addition Wizard!
============================================================

📝 Let's gather information about your new node...

🖥️  Step 1: Basic Node Information
----------------------------------------
Node name (e.g., 'laptop', 'server1'): rocketpool-node
Tailscale domain (e.g., 'mynode.tailnet.ts.net'): rp-server.tailnet.ts.net
SSH user [root]: ubuntu

🔗 Step 2: Testing Connection
----------------------------------------
Testing SSH connection to ubuntu@rp-server.tailnet.ts.net...
✅ Connection successful!

🔍 Step 3: Detecting Running Services
----------------------------------------
✅ Detected stacks: rocketpool, eth-docker
Use these detected stacks? [Y/n]: Y

⚙️  Step 4: Additional Configuration
----------------------------------------
Enable Ethereum execution/consensus clients? [Y/n]: Y

📋 Step 5: Configuration Summary
----------------------------------------
Node Name: rocketpool-node
Domain: rp-server.tailnet.ts.net
SSH User: ubuntu
Detected Stacks: rocketpool, eth-docker
Ethereum Clients: Enabled

Save this configuration? [Y/n]: Y

💾 Step 6: Saving Configuration
----------------------------------------
✅ Node 'rocketpool-node' added successfully!
📁 Configuration saved to: /home/egk/ethereumnodevalidatormanager/config.yaml

🎯 Next Steps
----------------------------------------
• Test the node: python3 -m eth_validators node list
• Check versions: python3 -m eth_validators node versions rocketpool-node
• View performance: python3 -m eth_validators performance summary
```

## Recursos Especiais

### 🔍 Detecção Inteligente de Stacks
- Analisa containers Docker em execução
- Identifica automaticamente:
  - Charon (Obol DVT)
  - Rocket Pool
  - Hyperdrive
  - SSV
  - Clients Ethereum padrão

### 🛡️ Validações de Segurança
- Verifica nomes duplicados
- Testa conectividade antes de salvar
- Valida domínios Tailscale únicos

### 📊 Integração Completa
Após adicionar um node, ele aparece automaticamente em:
- `node list` - Listagem geral
- `node versions` - Verificação de versões
- `performance summary` - Métricas de performance
- Todos os outros comandos do sistema

## Estado Atual vs. Novo Node

### Antes de Adicionar:
```bash
$ python3 -m eth_validators node list
🖥️  ETHEREUM NODE CLUSTER OVERVIEW
╒═════════════╤══════════╤═══════════════════════════╤═════════════════════════╕
│ Node Name   │ Status   │ Live Ethereum Clients     │ Stack                   │
╞═════════════╪══════════╪═══════════════════════════╪═════════════════════════╡
│ 🟢 testnode  │ Active   │ ⚙️  nethermind + 🔗 nimbus │ 🌐 charon + 🐳 eth-docker │
╘═════════════╧══════════╧═══════════════════════════╧═════════════════════════╛
📈 Total nodes: 1
```

### Depois de Adicionar:
```bash
$ python3 -m eth_validators node list
🖥️  ETHEREUM NODE CLUSTER OVERVIEW
╒══════════════════╤══════════╤═══════════════════════════╤═════════════════════════╕
│ Node Name        │ Status   │ Live Ethereum Clients     │ Stack                   │
╞══════════════════╪══════════╪═══════════════════════════╪═════════════════════════╡
│ 🟢 testnode       │ Active   │ ⚙️  nethermind + 🔗 nimbus │ 🌐 charon + 🐳 eth-docker │
│ 🟢 rocketpool-node│ Active   │ ⚙️  geth + 🔗 lighthouse  │ 🚀 rocketpool + 🐳 eth-docker │
╘══════════════════╧══════════╧═══════════════════════════╧═════════════════════════╛
📈 Total nodes: 2
```

## Vantagens do Processo Interativo

1. **🔄 Sem Edição Manual**: Não precisa editar YAML manualmente
2. **🔍 Detecção Automática**: Identifica automaticamente services rodando
3. **✅ Validação em Tempo Real**: Testa conectividade durante o processo
4. **🛡️ Previne Erros**: Valida duplicatas e configurações inválidas
5. **📚 Guia Passo-a-Passo**: Interface intuitiva similar ao quickstart
6. **🔧 Flexibilidade**: Permite override manual quando necessário

## Casos de Uso

- **Expansão de Cluster**: Adicionar novos nodes ao cluster existente
- **Migração**: Adicionar nodes migrados de outros setups
- **Teste**: Adicionar nodes temporários para testes
- **Diversificação**: Adicionar nodes com diferentes client stacks

Este comando torna a expansão do cluster tão simples quanto o setup inicial!
