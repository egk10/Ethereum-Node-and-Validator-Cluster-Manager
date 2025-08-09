#!/bin/bash

# Demo script para mostrar o processo interativo de adicionar um novo node

echo "🚀 DEMO: Como Adicionar um Novo Node Interativamente"
echo "=" * 60

echo ""
echo "📝 Processo para adicionar um novo node ao cluster:"
echo ""

echo "1️⃣ Execute o comando:"
echo "   python3 -m eth_validators node add-node"
echo ""

echo "2️⃣ O wizard vai pedir as informações básicas:"
echo "   • Nome do node (ex: 'server2', 'rp-node')"
echo "   • Domínio Tailscale (ex: 'mynode.tailnet.ts.net')"
echo "   • Usuário SSH (padrão: 'root')"
echo ""

echo "3️⃣ Teste de conectividade automático:"
echo "   ✅ Testa SSH connection"
echo "   ✅ Verifica se o node responde"
echo ""

echo "4️⃣ Detecção automática de stacks:"
echo "   🔍 Analisa 'docker ps' no node remoto"
echo "   🔍 Detecta: eth-docker, obol/charon, rocketpool, hyperdrive, ssv, etc."
echo "   ✅ Permite override manual se necessário"
echo ""

echo "5️⃣ Configuração adicional:"
echo "   ⚙️ Pergunta sobre Ethereum clients (execution/consensus)"
echo "   ⚙️ Detecta automaticamente nodes validator-only"
echo ""

echo "6️⃣ Resumo e confirmação:"
echo "   📋 Mostra todas as configurações"
echo "   💾 Salva no config.yaml existente"
echo ""

echo "🎯 Depois de adicionar, o node aparece em:"
echo "   • python3 -m eth_validators node list"
echo "   • python3 -m eth_validators node versions [nome_do_node]"
echo "   • python3 -m eth_validators performance summary"
echo ""

echo "💡 VANTAGENS do processo interativo:"
echo "   ✅ Sem edição manual de YAML"
echo "   ✅ Detecção automática de serviços" 
echo "   ✅ Validação em tempo real"
echo "   ✅ Previne configurações duplicadas"
echo "   ✅ Interface intuitiva como quickstart"
echo ""

echo "📊 EXEMPLO: Estado antes vs. depois"
echo ""
echo "ANTES:"
python3 -m eth_validators node list 2>/dev/null || echo "   [Atual cluster com 1 node]"

echo ""
echo "DEPOIS (simulado):"
echo "╒══════════════════╤══════════╤═══════════════════════════╤═════════════════════════╕"
echo "│ Node Name        │ Status   │ Live Ethereum Clients     │ Stack                   │"
echo "╞══════════════════╪══════════╪═══════════════════════════╪═════════════════════════╡"
echo "│ 🟢 testnode       │ Active   │ ⚙️  nethermind + 🔗 nimbus │ 🌐 charon + 🐳 eth-docker │"
echo "│ 🟢 server2        │ Active   │ ⚙️  geth + 🔗 lighthouse  │ 🚀 rocketpool + 🐳 eth-docker │"
echo "╘══════════════════╧══════════╧═══════════════════════════╧═════════════════════════╛"
echo ""

echo "🚀 Pronto! Cluster expandido automaticamente!"
