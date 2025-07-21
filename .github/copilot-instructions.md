<!-- Use this file to provide workspace-specific custom instructions to Copilot. For more details, visit https://code.visualstudio.com/docs/copilot/copilot-customization#_use-a-githubcopilotinstructionsmd-file -->

O projeto "Ethereum Validators Manager" é uma ferramenta CLI em Python para gerenciar um cluster de validadores Ethereum Mainnet. Ele permite listar status dos nós, automatizar upgrades de clientes via Docker, monitorar métricas e integrar gerenciamento via Tailscale domains.
O setup compreende diversos hardwares e stacks Ethereum clients rodando em Ubuntu Server 24.04+ com ETH-DOCKER.
Use as tabelas fornecidas para responder questões sobre o estado atual dos validadores, incluindo problemas e updates necessários.
Referências de stacks: eth-docker, NodeSet, Rocketpool, SSV, OBOL DV, StakeWise.
Para monitorar o desempenho e a saúde dos validadores, utilize as metricas disponibilizadas pelos clintes de consenso como Nimbus, Lighthouse, Teku, Grandine , Prysm, Vero, Lodestar e Lighthouse. Lighthouse fornece API especifica para desempenho vide https://lighthouse-book.sigmaprime.io/api_lighthouse.html https://lighthouse-book.sigmaprime.io/api_validator_inclusion.html O objetivo é calcular performance metrics aos moldes https://docs.rated.network/documentation/explorer/ethereum/network-views/pools-operators-and-validators/entity-metrics-drill-down#performance-metrics
https://docs.rated.network/documentation/methodologies/ethereum/rated-effectiveness-rating/raver-v3.0-current#attester-effectiveness
