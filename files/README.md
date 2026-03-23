# 🎯 VALORANT SCOUT AGENT
> **Análise Preditiva e Inteligência de Dados para o Cenário Competitivo**

Este projeto é uma ferramenta de **Data Analytics** avançada para VALORANT. Ele automatiza a coleta de dados de plataformas como **VLR.gg** e **Liquipedia**, processando estatísticas de performance individual e coletiva para gerar previsões estratégicas de confrontos e simulações de veto.

---

## 🚀 Diferenciais Técnicos (Arquitetura Big Data)

O agente utiliza uma abordagem **Lineup-Centric**: ele ignora o histórico estático da organização e foca na performance em tempo real dos 5 jogadores ativos.

### 🧠 Motor de Previsão (Combat Strength)
A força de combate é calculada via média ponderada de KPIs normalizados:

$$Strength = \frac{(W_{rating} \cdot R_{norm}) + (W_{kda} \cdot K_{norm}) + (W_{acs} \cdot A_{norm}) + (W_{fk} \cdot F_{norm})}{\sum W}$$

* **Normalização:** Dados escalonados (base 0-1) para evitar distorções de escala entre Rating e ACS.
* **Entropia Estatística:** O modelo injeta variação determinística baseada na "seed" do mapa para evitar resultados uniformes (50/50) em casos de falta de dados históricos.

### 📊 Nova Aba: Análise Detalhada & BI
* **Ranking Dinâmico:** Ranking dos 10 jogadores da partida ordenados por Rating ou ACS via Pandas.
* **Data Export:** Conversão instantânea da análise para **CSV (Excel Ready)** com codificação `utf-8-sig`.
* **Deep Scraping:** Mineração automática de dados na aba `/stats` e páginas individuais de jogadores.

---

## 🗺️ Localização dos Mapas (Base 2026)
O sistema mapeia as localidades dos 12 mapas oficiais (ex: Abyss/Noruega, Ascent/Itália, Bind/Marrocos, etc).

---

## 🛠️ Requisitos e Instalação

1. **Clone o repositório:**
   ```bash
   git clone [https://github.com/seu-usuario/valorant-scout-agent.git](https://github.com/seu-usuario/valorant-scout-agent.git)
   cd valorant-scout-agent