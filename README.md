# 🚀 Ethereum Node and Validator Cluster Manager

**Contributing to Ethereum decentralization**

Bem-vindo ao toolkit open source para manutenção, upgrade e monitoramento de validadores Ethereum Mainnet!  
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
    pip install -r requirements.txt
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
python3 -m eth_validators performance    # Performance dos validadores
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
- 🔍 **NOVO**: Compare versões em tempo real com GitHub - nunca mais fique para trás!
- 🚀 Suporte ao Grandine (o cliente consenso mais novo da galera!)
- 🌈 Veja sua diversidade de clientes numa tabela linda
- 🛠️ Open source: contribua, melhore e compartilhe com a comunidade Ethereum!

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