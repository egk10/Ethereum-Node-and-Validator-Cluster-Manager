# 🚀 Guia Rápido para Novos Usuários

## Ethereum Node and Validator Cluster Manager

### ⚡ Início Rápido (5 minutos)

```bash
# 1. Clone o repositório
git clone https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager.git
cd Ethereum-Node-and-Validator-Cluster-Manager

# 2. Instale as dependências
pip3 install -r requirements.txt

# 3. Configure automaticamente (wizard interativo)
python3 -m eth_validators quickstart

# 4. Descubra seus validators automaticamente
python3 -m eth_validators validator discover

# 5. Veja o status dos seus nodes
python3 -m eth_validators node list
```

### 🎯 Principais Comandos

#### **Descoberta Automática de Validators**
```bash
# Descobrir todos os validators automaticamente
python3 -m eth_validators validator discover

# Listar validators descobertos
python3 -m eth_validators validator list

# Filtrar por node específico
python3 -m eth_validators validator list --node mini1
```

#### **Monitoramento de Nodes**
```bash
# Status de todos os nodes
python3 -m eth_validators node list

# Versões dos clients Ethereum
python3 -m eth_validators node versions --all

# Upgrade de clients Docker
python3 -m eth_validators node upgrade --all
```

#### **Performance dos Validators**
```bash
# Resumo de performance
python3 -m eth_validators performance summary

# Análise detalhada por node
python3 -m eth_validators performance analyze --node mini1

# Métricas em tempo real
python3 -m eth_validators performance monitor
```

### 🔧 Pré-requisitos

1. **Tailscale configurado** nos seus nodes Ethereum
2. **SSH access** para os nodes remotos  
3. **Python 3.8+** no sistema de gerenciamento
4. **eth-docker/Hyperdrive** rodando nos nodes

### 📊 Stacks Suportadas

- ✅ **eth-docker**: Descoberta via `ethd keys list`
- ✅ **NodeSet Hyperdrive**: Descoberta via `hyperdrive sw v s`  
- ✅ **Obol DVT**: Charon container detection
- ✅ **Lido CSM**: Automated keystore scanning
- ✅ **Rocketpool**: Rocketpool data directory scanning

### 🚨 Solução de Problemas Comuns

#### "Não consegue conectar aos nodes"
```bash
# Verificar conectividade Tailscale
ping seu-node.tailnet.ts.net

# Testar SSH
ssh root@seu-node.tailnet.ts.net

# Verificar configuração
python3 -m eth_validators config validate
```

#### "Nenhum validator descoberto"
```bash
# Verificar se eth-docker está rodando
python3 -m eth_validators node status

# Forçar re-descoberta
python3 -m eth_validators validator discover --output fresh_discovery.csv

# Debug descoberta
python3 -c "from eth_validators.validator_auto_discovery import ValidatorAutoDiscovery; d = ValidatorAutoDiscovery('.'); print(d.discover_all_validators())"
```

#### "Erro de permissão SSH"
```bash
# Configurar chaves SSH
ssh-keygen -t rsa
ssh-copy-id root@seu-node.tailnet.ts.net

# Testar conexão
ssh -o ConnectTimeout=10 root@seu-node.tailnet.ts.net "echo 'Conexão OK'"
```

### 💡 Dicas para Novos Usuários

1. **Comece com `quickstart`** - configura tudo automaticamente
2. **Use descoberta automática** - elimina configuração manual de CSV
3. **Monitore regularmente** - `node list` e `performance summary`
4. **Mantenha clients atualizados** - `node upgrade --all`
5. **Backup da configuração** - `config.yaml` e CSVs são importantes

### 🆘 Suporte

- **GitHub Issues**: [Reportar bugs e sugestões](https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager/issues)
- **Documentação**: README.md para detalhes completos
- **Logs**: Use `--debug` em qualquer comando para diagnóstico

### 🎉 Próximos Passos

Depois do setup inicial:
1. Configure monitoramento automático
2. Explore dashboards Grafana  
3. Configure alertas de performance
4. Integre com seu sistema de monitoramento existente

**Bem-vindo ao gerenciamento profissional de validators Ethereum!** 🚀
