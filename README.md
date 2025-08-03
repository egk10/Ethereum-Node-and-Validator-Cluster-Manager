# 🚀 Ethereum Node and Validator Cluster Manager

[![GitHub release](https://img.shields.io/github/release/egk10/Ethereum-Node-and-Validator-Cluster-Manager.svg)](https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager/releases/latest)
[![Docker Pulls](https://img.shields.io/docker/pulls/egk10/ethereum-node-and-validator-cluster-manager.svg)](https://hub.docker.com/r/egk10/ethereum-node-and-validator-cluster-manager)

## Contributing to Ethereum decentralization

Sistema avançado para manutenção, upgrade e monitoramento de validadores Ethereum Mainnet com suporte multi-network!

## 🚀 Instalação Rápida

### Via Docker (Recomendado)

```bash
# Core (essencial)
docker run --rm egk10/ethereum-node-and-validator-cluster-manager:latest-core --help

# Com configuração
docker run -v $PWD/config:/config egk10/ethereum-node-and-validator-cluster-manager:latest-standard node status
```

### Via Download

```bash
# Baixar release mais recente
wget https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager/releases/latest/download/ethereum-validator-manager-core-v1.0.4.zip
unzip ethereum-validator-manager-core-v1.0.4.zip
cd ethereum-validator-manager-core-v1.0.4
./install.sh
```

## 📦 Tipos de Release

### 🎯 Core (~52KB) - Produção

```bash
docker pull egk10/ethereum-node-and-validator-cluster-manager:latest-core
```

### 🛠️ Standard (~59KB) - Core + Backup

```bash
docker pull egk10/ethereum-node-and-validator-cluster-manager:latest-standard
```

### 📊 Monitoring (~72KB) - Standard + Grafana

```bash  
docker pull egk10/ethereum-node-and-validator-cluster-manager:latest-monitoring
```

### 🧪 Full (~82KB) - Todos os recursos

```bash
docker pull egk10/ethereum-node-and-validator-cluster-manager:latest-full
```  
Este projeto foi criado para setups multi-hardware, multi-stack, com gerenciamento remoto via **Tailscale** e automação usando **ETH-DOCKER**.


## 🚦 Instalação Passo a Passo (para todos os níveis)

1. **Instale o Git e Python 3 (se ainda não tiver):**
    - No Ubuntu Server, execute:
      ```bash
      sudo apt update
      sudo apt install git python3 python3-venv
      ```

2. **Clone este repositório:**
    ```bash
    git clone https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager.git
    cd Ethereum-Node-and-Validator-Cluster-Manager
    ```

3. **Crie e ative um ambiente virtual Python (recomendado):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

4. **Instale as dependências do projeto:**
    ```bash
    # Core dependencies (required)
    pip install -r requirements.txt
    
    # Optional: ML dependencies for hybrid AI
    pip install -r requirements-ml.txt
    
    # Optional: LLM support (local)
    pip install ollama-python
    ```


5. **Configure seus arquivos de exemplo:**
    - Copie e renomeie os arquivos de exemplo para os nomes esperados pelo código:
      ```bash
      cp eth_validators/config.example.yaml eth_validators/config.yaml
      cp eth_validators/example_validators_vs_hardware.csv eth_validators/'validators vs hardware.csv'
      ```
    - Edite os arquivos `config.yaml` e `validators vs hardware.csv` conforme seu setup.
    - **Nunca compartilhe dados sensíveis!**

6. **(Opcional) Teste a instalação e o ambiente:**
    - Verifique se o ambiente virtual está ativo e as dependências instaladas:
      ```bash
      which python
      python --version
      pip list
      ```
    - Você pode rodar:
      ```bash
      python3 -m eth_validators --help
      ```
    - Isso deve mostrar os comandos disponíveis e confirmar que o toolkit está instalado corretamente.

7. **Execute o toolkit:**
    ```bash
    python3 -m eth_validators performance
    ```

---

## 📖 Como ver todos os comandos disponíveis (CLI)

Para ver todos os comandos e opções disponíveis, execute:

```bash
python3 -m eth_validators --help
```

### 🚀 **Comandos Principais:**

**📋 Informações dos Nodes:**
```bash
python3 -m eth_validators list           # Lista todos os nodes
python3 -m eth_validators status <node>  # Status detalhado + sincronização
```

**🐳 Gerenciamento Docker/Ethereum:**
```bash
python3 -m eth_validators client-versions         # 🔍 Versões atuais vs GitHub (todos) - NOVO!
python3 -m eth_validators client-versions <node>  # 🔍 Versões atuais vs GitHub (um node) - NOVO!
python3 -m eth_validators upgrade <node>          # 🚀 Upgrade Docker de um node
python3 -m eth_validators upgrade-all             # 🚀 Upgrade Docker de todos os nodes
python3 -m eth_validators versions <node>         # 📦 Versões dos clientes de um node
python3 -m eth_validators versions-all            # 📦 Versões de todos os nodes
```

**🖥️ Gerenciamento Sistema Ubuntu:**
```bash
python3 -m eth_validators system-updates            # Verifica atualizações (todos)
python3 -m eth_validators system-updates <node>     # Verifica atualizações (um node)
python3 -m eth_validators system-upgrade <node>     # Atualiza sistema de um node
python3 -m eth_validators system-upgrade --all      # Atualiza sistema (apenas nodes que precisam)
python3 -m eth_validators system-upgrade --all --force  # Força atualização de todos
```

**📊 Monitoramento:**
```bash
python3 -m eth_validators performance        # Performance dos validadores
python3 -m eth_validators analyze-node <node>  # 🆕 Análise detalhada de validadores por node
```

**🧠 AI-Powered Analysis (NOVO!):**
```bash
python3 -m eth_validators ai-health              # 🏥 Health scores AI para todos os nodes
python3 -m eth_validators ai-health <node>       # 🏥 Health score AI para um node específico
python3 -m eth_validators ai-analyze <node>      # 🧠 Análise completa AI de logs e performance
python3 -m eth_validators ai-patterns <node>     # 🔍 Detecção de padrões temporais com AI
python3 -m eth_validators ai-recommend <node>    # 💡 Recomendações AI para otimização
```

Isso mostrará a lista de comandos e instruções de uso do toolkit.

---

## 🧑‍💻 O que este projeto faz?

- 🎯 Gerencia múltiplos nodes e clientes (Nethermind, Reth, Lighthouse, Nimbus, Grandine, etc)
- 🔄 Facilita upgrades de **clientes Ethereum** (Docker containers)
- 🛡️ Automatiza **atualizações do sistema Ubuntu** com verificação inteligente
- 📊 Monitora performance, sync status e troubleshooting
- 🌐 Usa domínios Tailscale para acesso remoto seguro e estável
- 💰 Suporta diferentes Withdrawal Credentials e Fee Recipients por hardware
- 🔧 Compatível com stacks: ETH-DOCKER, Rocketpool, Node Set Hyperdrive, SSV, OBOL DV e outros
- 🔍 **NOVO**: Compara versões locais com GitHub releases em tempo real!

---

## 🛠️ Como usar

1. **Clone o repositório:**
    ```bash
    git clone https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager.git
    cd Ethereum-Node-and-Validator-Cluster-Manager
    ```

2. **Crie e ative um ambiente virtual Python:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

3. **Configure seu arquivo de configuração:**
    - Copie o arquivo de exemplo:
      ```bash
      cp eth_validators/config.example.yaml eth_validators/config.yaml
      ```
    - Edite `config.yaml` com seus nodes e configurações
    - **Importante**: Para atualizações do sistema Ubuntu, configure:
      - `ssh_user: "root"` (recomendado), OU
      - Configure sudo sem senha para o usuário no node remoto

4. **Configure seu arquivo de validadores:**
    - O projeto espera um arquivo chamado `validators vs hardware.csv` na pasta `eth_validators/`
    - **Nunca compartilhe chaves privadas ou dados sensíveis!**

5. **Execute os comandos:**
    ```bash
    # Verificar status dos nodes
    python3 -m eth_validators status laptop
    
    # Upgrade Docker dos clientes Ethereum
    python3 -m eth_validators upgrade laptop
    
    # Verificar e atualizar sistema Ubuntu
    python3 -m eth_validators system-updates
    python3 -m eth_validators system-upgrade --all
    
    # Performance dos validadores
    python3 -m eth_validators performance
    ```

## ⚠️ **Configuração SSH para Atualizações do Sistema**

Para usar os comandos `system-upgrade`, você precisa de uma dessas configurações:

### **Opção 1: Usuário Root (Recomendado)**
```yaml
# No seu config.yaml
- name: "meu-node"
  ssh_user: "root"
  tailscale_domain: "node.meu-tailnet.ts.net"
```

### **Opção 2: Sudo sem Senha**
Se preferir usar um usuário não-root, configure sudo sem senha no node remoto:
```bash
# SSH no node remoto
ssh usuario@node.meu-tailnet.ts.net

# Adicionar sudo sem senha
echo "usuario ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/usuario
```

---

## 💡 **Exemplos de Uso Prático**

### **Fluxo Completo de Manutenção:**

```bash
# 1. Verificar status geral
python3 -m eth_validators list
python3 -m eth_validators performance

# 2. 🔍 NOVO: Verificar versões dos clientes vs GitHub releases
python3 -m eth_validators client-versions

# 3. Verificar se há atualizações do sistema Ubuntu
python3 -m eth_validators system-updates

# 4. Atualizar sistema Ubuntu (apenas nodes que precisam)
python3 -m eth_validators system-upgrade --all

# 5. Atualizar clientes Ethereum se necessário
python3 -m eth_validators upgrade-all

# 6. Verificar sincronização após upgrades
python3 -m eth_validators status laptop
python3 -m eth_validators status minipcamd
```

### **Gerenciamento Individual:**

```bash
# Status detalhado de um node específico
python3 -m eth_validators status laptop

# 🔍 NOVO: Verificar versões de clientes vs GitHub (um node)
python3 -m eth_validators client-versions laptop

# Upgrade apenas Docker de um node
python3 -m eth_validators upgrade laptop

# Upgrade apenas sistema Ubuntu de um node
python3 -m eth_validators system-upgrade laptop

# Versões dos clientes instalados (sem GitHub)
python3 -m eth_validators versions laptop
```

### **Análise Multi-Stack (NOVO):**

```bash
# 🆕 Análise detalhada de nodes multi-stack
python3 -m eth_validators analyze-node minipcamd3

# Exibe todos os validadores, protocolos e containers de um node
# Especialmente útil para setups complexos como:
# - Stakewise + Obol DVT no mesmo hardware
# - Múltiplos validator clients (Teku + Lodestar)
# - Validadores em diferentes protocolos
```

### **Modo Inteligente vs Força:**

```bash
# Modo inteligente: só atualiza nodes que precisam
python3 -m eth_validators system-upgrade --all

# Modo força: atualiza todos independente da necessidade
python3 -m eth_validators system-upgrade --all --force
```

---

## 🦄 Por que é divertido?

- 🎯 Chega de IPs dinâmicos: use domínios Tailscale!
- 🔄 Misture clientes e stacks para máxima resiliência.
- 🔍 **NOVO**: Compara versões em tempo real com GitHub - nunca mais fique para trás!
- 🧠 **REVOLUCIONÁRIO**: Sistema de análise AI para logs, padrões e recomendações inteligentes!
- 🏥 **Health Scores AI**: Pontuação de saúde automatizada com detecção de anomalias
- � **Padrões Temporais**: Detecção inteligente de problemas recorrentes e tendências
- 💡 **Recomendações AI**: Sugestões personalizadas para otimização e resolução de problemas
- �🚀 Suporte ao Grandine (o cliente consenso mais novo da galera!)
- 🌈 Veja sua diversidade de clientes numa tabela linda
- 🛠️ Open source: contribua, melhore e compartilhe com a comunidade Ethereum!

---

## 🧠 **Sistema de Análise AI (REVOLUCIONÁRIO!)**

Este toolkit agora inclui um sistema avançado de análise AI que monitora seus validadores 24/7, detecta anomalias, identifica padrões e fornece recomendações inteligentes para otimização.

### **🏥 Health Monitoring AI**

```bash
# Health score de todos os nodes
python3 -m eth_validators ai-health

# Health score de um node específico
python3 -m eth_validators ai-health laptop --threshold 80
```

**O que o AI Health faz:**
- 🎯 Calcula pontuação de saúde (0-100%) baseada em múltiplos fatores
- ⚠️ Detecta anomalias automaticamente em logs e métricas
- 🔴 Identifica nodes críticos que precisam atenção imediata
- 📊 Análise de padrões de erro e warning ao longo do tempo
- 🚨 Alertas inteligentes baseados em thresholds configuráveis

### **🧠 Análise Completa AI**

```bash
# Análise AI completa de um node
python3 -m eth_validators ai-analyze laptop

# Análise focada em container específico
python3 -m eth_validators ai-analyze laptop --container lighthouse-validator-client

# Análise das últimas 48 horas com logs DEBUG
python3 -m eth_validators ai-analyze laptop --hours 48 --severity DEBUG
```

**Capacidades da Análise AI:**
- 🔍 **Análise de Logs Inteligente**: Processamento automático de gigabytes de logs
- 🎯 **Detecção de Anomalias**: Algoritmos ML para identificar comportamentos anômalos
- 📈 **Métricas de Performance**: Análise estatística de efficiency, misses, inclusion distance
- 🔄 **Padrões Temporais**: Identificação de problemas recorrentes e tendências
- 💾 **Uso de Recursos**: Monitoramento de CPU, RAM, disco e rede
- 🌐 **Conectividade**: Análise de peer connections e network health

### **🔍 Detecção de Padrões AI**

```bash
# Análise de padrões da última semana
python3 -m eth_validators ai-patterns laptop --days 7

# Foco específico em padrões de erro
python3 -m eth_validators ai-patterns laptop --pattern-type errors

# Análise de padrões de performance
python3 -m eth_validators ai-patterns laptop --pattern-type performance --days 30
```

**Tipos de Padrões Detectados:**
- 🕐 **Padrões Temporais**: Problemas que ocorrem em horários específicos
- 🔄 **Problemas Recorrentes**: Issues que se repetem periodicamente
- 📊 **Degradação de Performance**: Tendências de queda na efficiency
- 🌐 **Problemas de Rede**: Padrões de conectividade e peer issues
- 💾 **Gargalos de Recursos**: Identificação de limitações de hardware

### **💡 Recomendações AI**

```bash
# Recomendações gerais para otimização
python3 -m eth_validators ai-recommend laptop

# Foco em performance
python3 -m eth_validators ai-recommend laptop --focus performance

# Foco em confiabilidade
python3 -m eth_validators ai-recommend laptop --focus reliability

# Foco em segurança
python3 -m eth_validators ai-recommend laptop --focus security
```

**Tipos de Recomendações:**
- ⚡ **Otimização de Performance**: Configurações para melhorar efficiency
- 🛡️ **Melhorias de Confiabilidade**: Sugestões para reduzir downtime
- 🔒 **Hardening de Segurança**: Recomendações de segurança personalizadas
- 🔧 **Ajustes de Configuração**: Otimizações específicas por cliente
- 📈 **Scaling Suggestions**: Recomendações para crescimento da infraestrutura

### **🎯 Exemplo de Fluxo AI Completo**

```bash
# 1. Verificação rápida de saúde
python3 -m eth_validators ai-health

# 2. Se algum node estiver com problemas, análise detalhada
python3 -m eth_validators ai-analyze minipcamd3

# 3. Investigação de padrões se necessário
python3 -m eth_validators ai-patterns minipcamd3 --days 14

# 4. Obter recomendações específicas
python3 -m eth_validators ai-recommend minipcamd3 --focus reliability

# 5. Implementar melhorias e monitorar
python3 -m eth_validators ai-health minipcamd3 --threshold 90
```

### **🔮 Tecnologia AI Implementada**

- **Machine Learning**: Algoritmos de detecção de anomalias e pattern matching
- **Statistical Analysis**: Análise estatística avançada de métricas temporais
- **Natural Language Processing**: Processamento inteligente de logs textuais
- **Predictive Analytics**: Identificação precoce de problemas potenciais
- **Adaptive Thresholds**: Limites dinâmicos baseados no comportamento histórico

---

## 📚 Referências úteis

- [ETH-DOCKER](https://ethdocker.com/)
- [Node Set Hyperdrive](https://docs.nodeset.io/)
- [Lido CSM](https://csm.lido.fi/)
- [Client Diversity](https://clientdiversity.org/#distribution)
- [Rocketpool](https://docs.rocketpool.net/)
- [SSV Network](https://docs.ssv.network/operators/)
- [Obol Network](https://docs.obol.org/)
- [Stakewise](https://docs.stakewise.io/)
- [VERO multi-node validator client software](https://github.com/serenita-org/vero/tree/master)

---

## 📝 License

MIT — Open source, public good!

---

**Have fun, stay decentralized, and may your validators always be in sync!**

---

## ⚠️ Segurança

### **Arquivos a NÃO incluir no Git:**
- Adicione ao `.gitignore`:
    ```
    eth_validators/validators vs hardware.csv
    eth_validators/config.yaml
    venv/
    .venv/
    __pycache__/
    *.pyc
    .env
    ```

### **Configuração SSH Segura:**
- Use chaves SSH em vez de senhas
- Configure Tailscale para acesso remoto seguro
- Para sudo sem senha, configure apenas em nodes confiáveis
- Nunca compartilhe arquivos de configuração com dados sensíveis

### **Dados Sensíveis:**
- **NUNCA** faça commit de:
  - Chaves privadas de validadores
  - Arquivos de configuração com domínios reais
  - Dados de performance que possam identificar seus validadores
- Use arquivos `.example` para templates públicos