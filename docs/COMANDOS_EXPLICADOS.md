# 📚 Guia: Diferenças Entre os Grupos de Comandos

## 🤔 A Confusão Está Esclarecida!

Você tem razão - alguns comandos podem parecer similares. Vou explicar exatamente o que cada grupo faz e quando usar cada um.

## 🔧 `config` vs 🖥️ `node` - A Diferença Principal

### 🔧 **Grupo `config`** = **CONFIGURAÇÃO DO SISTEMA**
**Foco**: Gerenciar o arquivo `config.yaml` e descobrir configurações automaticamente

```bash
python3 -m eth_validators config discover  # Descobre nodes na rede e atualiza config.yaml
python3 -m eth_validators config sync-all  # Sincroniza config.yaml com estado real dos nodes
python3 -m eth_validators config validate  # Verifica se config.yaml está correto
python3 -m eth_validators config monitor   # Monitora mudanças nos nodes automaticamente
```

**Quando usar `config`**:
- ✅ Quando você quer **atualizar o config.yaml** automaticamente
- ✅ Quando você **adicionou/removeu** containers mas não atualizou o config
- ✅ Para **descobrir nodes novos** na rede automaticamente
- ✅ Para **validar** se suas configurações estão corretas

---

### 🖥️ **Grupo `node`** = **OPERAÇÕES NOS NODES**
**Foco**: Gerenciar e operar os nodes que JÁ estão no config.yaml

```bash
python3 -m eth_validators node list        # Mostra status atual de todos os nodes
python3 -m eth_validators node versions    # Verifica versões dos clients nos nodes
python3 -m eth_validators node upgrade     # Atualiza containers Docker nos nodes
python3 -m eth_validators node add-node    # Adiciona um novo node via wizard interativo
```

**Quando usar `node`**:
- ✅ Para **ver status atual** dos seus nodes
- ✅ Para **atualizar software** (Docker containers)
- ✅ Para **adicionar um novo node** interativamente
- ✅ Para **operar** nodes que já existem no config

---

## 📊 Comparação Prática

### Cenário 1: "Tenho um node novo na rede mas não está no config.yaml"

**❌ ERRADO**: `python3 -m eth_validators node list` → Não vai mostrar o node
**✅ CERTO**: `python3 -m eth_validators config discover` → Encontra e adiciona ao config

### Cenário 2: "Quero adicionar um node manualmente"

**❌ ERRADO**: `python3 -m eth_validators config sync-all` → Só funciona para nodes já na rede
**✅ CERTO**: `python3 -m eth_validators node add-node` → Wizard interativo para adicionar

### Cenário 3: "Quero ver o status dos meus nodes"

**❌ ERRADO**: `python3 -m eth_validators config summary` → Mostra estatísticas do config
**✅ CERTO**: `python3 -m eth_validators node list` → Mostra status em tempo real

### Cenário 4: "Mudei configurações nos containers mas config.yaml está desatualizado"

**❌ ERRADO**: `python3 -m eth_validators node versions` → Mostra versões mas não atualiza config
**✅ CERTO**: `python3 -m eth_validators config sync-all` → Sincroniza config com estado real

---

## 🎯 Resumo dos 7 Grupos Principais

| Grupo | Foco | Quando Usar |
|-------|------|-------------|
| **🚀 quickstart** | Setup inicial | Primeira vez configurando o sistema |
| **🔧 config** | Configuração/discovery | Quando config.yaml está desatualizado |
| **🖥️ node** | Operações nos nodes | Para gerenciar nodes já configurados |
| **📊 performance** | Métricas validators | Ver performance dos seus validadores |
| **👥 validator** | Gestão validators | Migrar/editar validadores |
| **⚙️ system** | Sistema/updates | Atualizações de SO dos nodes |
| **🧠 ai** | Análise inteligente | Detectar problemas via AI |

---

## 💡 Workflows Típicos

### 🔄 **Workflow 1: Novo Usuário**
```bash
1. python3 -m eth_validators quickstart           # Setup inicial
2. python3 -m eth_validators node list            # Ver nodes configurados
3. python3 -m eth_validators performance summary  # Ver performance
```

### 📈 **Workflow 2: Adicionar Node**
```bash
1. python3 -m eth_validators node add-node        # Adicionar via wizard
2. python3 -m eth_validators node list            # Confirmar que apareceu
3. python3 -m eth_validators node versions NOME   # Verificar versões
```

### 🔍 **Workflow 3: Descobrir Mudanças**
```bash
1. python3 -m eth_validators config discover      # Descobrir novos nodes
2. python3 -m eth_validators config sync-all      # Sincronizar configurações
3. python3 -m eth_validators node list            # Ver estado atual
```

### 🚀 **Workflow 4: Manutenção**
```bash
1. python3 -m eth_validators node versions --all  # Ver o que precisa atualizar
2. python3 -m eth_validators node upgrade --all   # Atualizar containers
3. python3 -m eth_validators system upgrade --all # Atualizar SO se necessário
```

---

## ⚡ Comandos Mais Úteis no Dia-a-Dia

### 📱 **Dashboard Rápido**
```bash
python3 -m eth_validators node list               # Status geral
python3 -m eth_validators performance summary     # Performance validators
```

### 🔧 **Manutenção Semanal**
```bash
python3 -m eth_validators node versions --all     # Check updates
python3 -m eth_validators config sync-all         # Sync configurations
```

### 🆘 **Troubleshooting**
```bash
python3 -m eth_validators ai health               # Análise AI
python3 -m eth_validators node inspect NOME      # Debug específico
```

---

## 🎉 Conclusão

**A regra é simples**:
- **`config`** = Mexer no arquivo de configuração
- **`node`** = Mexer nos nodes em si
- **`performance`** = Ver como estão os validadores
- **`quickstart`** = Começar do zero

Cada grupo tem uma responsabilidade específica, evitando duplicação e mantendo as coisas organizadas! 🚀
