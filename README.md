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

7. **Execute o toolkit:**
    ```bash
    python3 -m eth_validators performance
    ```

---

## 🧑‍💻 O que este projeto faz?

- Gerencia múltiplos nodes e clientes (Nethermind, Reth, Lighthouse, Nimbus, etc)
- Facilita upgrades, monitoramento e troubleshooting
- Usa domínios Tailscale para acesso remoto seguro e estável
- Suporta diferentes Withdrawal Credentials e Fee Recipients por hardware
- Compatível com stacks: ETH-DOCKER, Rocketpool, Node Set Hyperdrive, SSV, OBOL DV e outros

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

3. **Crie seu arquivo de configuração de validadores:**
    - O projeto espera um arquivo chamado `validators vs hardware.csv` na pasta `eth_validators/`.
    - **Nunca compartilhe chaves privadas ou dados sensíveis!**
    - Exemplo de formato:
        ```
        validator index,validator public address,Protocol,stack,tailscale dns,AI Monitoring containers1,AI Monitoring containers2,AI Monitoring containers3,AI Monitoring containers4
        1634582,0xabc...,102 CSM LIDO,VERO,minipcamd.velociraptor-scylla.ts.net,eth-docker-validator-1,eth-docker-consensus-1,eth-docker-execution-1,eth-docker-mev-boost-1
        ```
    - Cada linha representa um validador e seu hardware correspondente.

4. **Edite o `config.yaml` conforme seu setup.**

5. **Execute o toolkit:**
    ```bash
    python3 -m eth_validators performance
    ```

---

## 🦄 Por que é divertido?

- Chega de IPs dinâmicos: use domínios Tailscale!
- Misture clientes e stacks para máxima resiliência.
- Open source: contribua, melhore e compartilhe com a comunidade Ethereum!

---

## 📚 Referências úteis

- [ETH-DOCKER](https://ethdocker.com/)
- [Node Set Hyperdrive](https://docs.nodeset.io/)
- [Lido CSM](https://csm.lido.fi/)
- [Client Diversity](https://clientdiversity.org/#distribution)
- [Rocketpool](https://docs.rocketpool.net/guides/node/updates.html)
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

- Adicione ao `.gitignore`:
    ```
    eth_validators/validators vs hardware.csv
    venv/
    __pycache__/
    *.pyc
    .env
    ```
- Nunca faça commit de arquivos com dados