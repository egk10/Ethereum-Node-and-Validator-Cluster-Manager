# Ethereum Validator Manager Release System

Este documento explica como usar o sistema de releases modulares do Ethereum Validator Manager.

## Tipos de Release

### Core (Essencial)
- Funcionalidades básicas de gerenciamento de validadores
- Comandos: status, upgrade, versions-all
- Ideal para: Usuários que só precisam do essencial
- Tamanho: ~1MB

### Standard (Padrão) 
- Inclui tudo do Core +
- Módulos de backup e performance
- Ideal para: Uso geral em produção
- Tamanho: ~2MB

### Monitoring (Monitoramento)
- Inclui tudo do Standard +
- Integração com Grafana e Prometheus
- Ideal para: Setups com monitoramento completo
- Tamanho: ~5MB

### Full (Completo)
- Inclui todos os módulos
- Recursos experimentais (AI, etc.)
- Ideal para: Desenvolvimento e testes
- Tamanho: ~10MB

## Build Local

### Preparação do Ambiente
```bash
# Instalar dependências
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Tornar scripts executáveis
chmod +x build_release.py
chmod +x build_docker.sh
chmod +x test_release.py
```

### Gerando Releases
```bash
# Release core
python3 build_release.py --version 1.0.0 --type core

# Release standard
python3 build_release.py --version 1.0.0 --type standard

# Release monitoring
python3 build_release.py --version 1.0.0 --type monitoring

# Release full
python3 build_release.py --version 1.0.0 --type full

# Todos os tipos
python3 build_release.py --version 1.0.0 --all
```

### Build Docker
```bash
# Build image core
docker build --target core -t ethereum-validator-manager:core .

# Build image standard
docker build --target standard -t ethereum-validator-manager:standard .

# Build image monitoring  
docker build --target monitoring -t ethereum-validator-manager:monitoring .

# Build image full
docker build --target full -t ethereum-validator-manager:full .

# Build todas as images
./build_docker.sh
```

### Testando
```bash
# Executar testes completos
python3 test_release.py

# Testar release específica
unzip dist/ethereum-validator-manager-core-v1.0.0.zip
cd ethereum-validator-manager-core-v1.0.0
chmod +x install.sh
./install.sh
```

## Release Automático (GitHub)

### Configuração Inicial
1. Configure secrets no GitHub:
   - `DOCKERHUB_USERNAME`: Usuário Docker Hub
   - `DOCKERHUB_TOKEN`: Token Docker Hub

2. Habilite GitHub Actions no repositório

### Criando Release
```bash
# Tag para release
git tag v1.0.0
git push origin v1.0.0

# Ou criar release manual no GitHub
# Isso irá disparar automaticamente:
# - Build de todos os tipos de release
# - Build de todas as images Docker
# - Upload dos artefatos para GitHub
# - Push das images para Docker Hub
```

### Artefatos Gerados
- `ethereum-validator-manager-core-v1.0.0.zip`
- `ethereum-validator-manager-standard-v1.0.0.zip`  
- `ethereum-validator-manager-monitoring-v1.0.0.zip`
- `ethereum-validator-manager-full-v1.0.0.zip`
- Docker images em Docker Hub

## Instalação

### A partir do ZIP
```bash
# Download do GitHub Releases
wget https://github.com/seu-usuario/ethereum-validator-manager/releases/download/v1.0.0/ethereum-validator-manager-standard-v1.0.0.zip

# Extrair e instalar
unzip ethereum-validator-manager-standard-v1.0.0.zip
cd ethereum-validator-manager-standard-v1.0.0
chmod +x install.sh
sudo ./install.sh
```

### A partir do Docker
```bash
# Executar diretamente
docker run --rm -v /path/to/config:/config ethereum-validator-manager:standard status

# Executar interativo
docker run -it --rm -v /path/to/config:/config ethereum-validator-manager:standard bash
```

## Estrutura dos Módulos

### Core (Sempre Incluído)
- `cli.py` - Interface CLI principal
- `config.py` - Configuração
- `node_manager.py` - Gerenciamento de nodes

### Opcionais
- `backup.py` - Sistema de backup
- `performance.py` - Análise de performance
- `grafana.py` - Integração Grafana
- `prometheus.py` - Métricas Prometheus  
- `ai.py` - Recursos AI (experimental)

## Troubleshooting

### Erro no Build
```bash
# Verificar dependências
pip install -r requirements.txt

# Limpar cache
rm -rf dist/ __pycache__/ eth_validators/__pycache__/

# Rebuild
python3 build_release.py --version 1.0.0 --type core
```

### Erro no Docker
```bash
# Verificar Docker
docker --version

# Limpar images
docker system prune -f

# Rebuild
docker build --no-cache --target core -t ethereum-validator-manager:core .
```

### Erro na Instalação
```bash
# Verificar permissões
chmod +x install.sh

# Instalar como root
sudo ./install.sh

# Verificar PATH
which ethereum-validator-manager
```

## Personalização

Para adicionar novos módulos ao sistema de releases:

1. Edite `release_config.py`:
```python
OPTIONAL_MODULES = {
    'meu_modulo': {
        'files': ['eth_validators/meu_modulo.py'],
        'dependencies': ['minha-dependencia']
    }
}
```

2. Atualize `RELEASE_TYPES`:
```python
'meu_tipo': {
    'modules': ['meu_modulo'],
    'description': 'Descrição do meu tipo'
}
```

3. Rebuild o sistema.
