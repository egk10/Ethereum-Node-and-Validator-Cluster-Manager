#!/bin/bash

# 🚀 Script de desenvolvimento para melhorias de experiência do usuário novo
# Autor: egk10
# Data: $(date +%Y-%m-%d)

set -e  # Parar em caso de erro

BRANCH_NAME="feature/new-user-experience-improvements"
REPO_PATH="/home/egk/ethereumnodevalidatormanager"

echo "🚀 ETHEREUM VALIDATOR CLUSTER MANAGER - DESENVOLVIMENTO"
echo "=========================================================="
echo "Branch: $BRANCH_NAME"
echo "Path: $REPO_PATH"
echo

# Função para mostrar status atual
show_status() {
    echo "📊 Status Atual:"
    echo "   Branch: $(git branch --show-current)"
    echo "   Último commit: $(git log --oneline -1)"
    echo "   Arquivos modificados: $(git status --porcelain | wc -l)"
    echo
}

# Função para testar como usuário novo
test_new_user_experience() {
    echo "🧪 TESTANDO EXPERIÊNCIA DE USUÁRIO NOVO"
    echo "----------------------------------------"
    
    echo "1️⃣ Testando comandos básicos..."
    python3 -m eth_validators --help | head -10
    
    echo -e "\n2️⃣ Testando descoberta automática de validators..."
    python3 -m eth_validators validator discover --help
    
    echo -e "\n3️⃣ Testando quickstart..."
    python3 -m eth_validators quickstart --help
    
    echo -e "\n4️⃣ Testando listagem de nodes..."
    python3 -m eth_validators node list --help
    
    echo -e "\n✅ Testes básicos concluídos!"
}

# Função para fazer commit das mudanças
commit_changes() {
    echo "💾 FAZENDO COMMIT DAS MUDANÇAS"
    echo "-------------------------------"
    
    git add .
    echo "Arquivos adicionados ao staging."
    
    read -p "📝 Digite a mensagem do commit: " commit_message
    
    if [ -n "$commit_message" ]; then
        git commit -m "$commit_message"
        echo "✅ Commit realizado com sucesso!"
    else
        echo "❌ Mensagem de commit não pode estar vazia."
        return 1
    fi
}

# Função para fazer merge para main
merge_to_main() {
    echo "🔄 FAZENDO MERGE PARA MAIN"
    echo "--------------------------"
    
    echo "Mudando para branch main..."
    git checkout main
    
    echo "Fazendo merge da branch $BRANCH_NAME..."
    git merge $BRANCH_NAME
    
    echo "Fazendo push das mudanças..."
    git push origin main
    
    echo "✅ Merge concluído com sucesso!"
    
    echo "Voltando para branch de desenvolvimento..."
    git checkout $BRANCH_NAME
}

# Função para testar em ambiente limpo
test_clean_environment() {
    echo "🧹 TESTANDO EM AMBIENTE LIMPO"
    echo "------------------------------"
    
    CLEAN_TEST_DIR="/tmp/ethereum-validator-clean-test-$(date +%s)"
    
    echo "Criando ambiente de teste limpo em: $CLEAN_TEST_DIR"
    git clone https://github.com/egk10/Ethereum-Node-and-Validator-Cluster-Manager.git $CLEAN_TEST_DIR
    
    cd $CLEAN_TEST_DIR
    
    echo "Instalando dependências..."
    pip3 install -r requirements.txt
    
    echo "Testando quickstart..."
    python3 -m eth_validators quickstart --help
    
    echo "Testando descoberta de validators..."
    python3 -m eth_validators validator discover --help
    
    cd $REPO_PATH
    
    echo "✅ Teste em ambiente limpo concluído!"
    echo "📁 Pasta de teste: $CLEAN_TEST_DIR"
    echo "   (pode ser removida com: rm -rf $CLEAN_TEST_DIR)"
}

# Menu principal
show_menu() {
    echo "🎯 MENU DE DESENVOLVIMENTO:"
    echo "1) Ver status atual"
    echo "2) Testar experiência de usuário novo"
    echo "3) Fazer commit das mudanças"
    echo "4) Fazer merge para main e push"
    echo "5) Testar em ambiente completamente limpo"
    echo "6) Sair"
    echo
}

# Loop principal
cd $REPO_PATH

# Garantir que estamos na branch correta
git checkout $BRANCH_NAME 2>/dev/null || {
    echo "❌ Branch $BRANCH_NAME não existe. Criando..."
    git checkout -b $BRANCH_NAME
}

while true; do
    show_menu
    read -p "Escolha uma opção (1-6): " choice
    echo
    
    case $choice in
        1)
            show_status
            ;;
        2)
            test_new_user_experience
            ;;
        3)
            commit_changes
            ;;
        4)
            merge_to_main
            ;;
        5)
            test_clean_environment
            ;;
        6)
            echo "👋 Saindo do script de desenvolvimento. Boa codificação!"
            exit 0
            ;;
        *)
            echo "❌ Opção inválida. Tente novamente."
            ;;
    esac
    
    echo
    read -p "Pressione Enter para continuar..."
    echo
done
