"""
scraper.py — VALORANT SCOUT AGENT
Web scraping VLR.gg e Liquipedia.
 
ARQUITETURA CONFIRMADA COM HTML REAL (março 2026):
─────────────────────────────────────────────────
• Página do TIME  (/team/ID/nome):
    - Roster em  div.team-roster-item  >  .team-roster-item-name-alias
    - Roles ficam em .team-roster-item-name-role (vazio para jogadores ativos,
      "Sub" / "head coach" / "assistant coach" para não-jogadores)
    - Links de player: a[href*='/player/']
 
• Página do PLAYER (/player/ID/nome):
    - ÚNICA tabela: table.wf-table — stats POR AGENTE (não existe linha "total")
    - Headers: '' | Use | RND | Rating2.0 | ACS | K:D | ADR | KAST |
               KPR | APR | FKPR | FDPR | K | D | A | FK | FD
    - Índices:   0     1    2       3      4    5    6     7
                  8    9    10    11    12  13  14  15  16
    - Stats gerais = MÉDIA PONDERADA por RND (rounds jogados com cada agente)
    - Role = agente com mais rounds → AGENT_ROLE_MAP
 
• Página /team/stats/ID/nome:
    - Contém APENAS stats por mapa (Win%, W, L) — NÃO tem stats de players.
    - NÃO É USADA para extrair dados de jogadores.
"""
 
import requests
from bs4 import BeautifulSoup
import re, time, random, json, os
from datetime import datetime, timedelta
from collections import Counter
from typing import Optional
 
from models import ALL_MAP_NAMES, MAP_POOL_HISTORY
 
# ─── Constantes ───────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection":      "keep-alive",
    "Referer":         "https://www.vlr.gg/",
}
 
VLR_BASE        = "https://www.vlr.gg"
LIQUIPEDIA_BASE = "https://liquipedia.net"
CACHE_DIR       = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
CACHE_TTL       = timedelta(hours=24)
 
# ── Tokens de não-jogador ─────────────────────────────────────────────────────
# Confirmados com HTML real: role='Sub', 'head coach', 'assistant coach'
NON_PLAYER_TOKENS = {
    "coach", "head coach", "assistant coach",
    "staff", "manager", "analyst",
    "trainer", "sub", "substitute",
    "director", "owner",
}
 
# ── Agente → role ─────────────────────────────────────────────────────────────
AGENT_ROLE_MAP: dict[str, str] = {
    "jett":"Duelist",  "reyna":"Duelist",  "phoenix":"Duelist",
    "raze":"Duelist",  "yoru":"Duelist",   "neon":"Duelist",
    "iso":"Duelist",   "waylay":"Duelist",
    "sova":"Initiator","breach":"Initiator","skye":"Initiator",
    "kayo":"Initiator","fade":"Initiator",  "gekko":"Initiator",
    "tejo":"Initiator",
    "brimstone":"Controller","viper":"Controller","omen":"Controller",
    "astra":"Controller","harbor":"Controller","clove":"Controller",
    "vyse":"Controller",
    "killjoy":"Sentinel","cypher":"Sentinel","sage":"Sentinel",
    "chamber":"Sentinel","deadlock":"Sentinel",
}
 
# ── Mapa canônico ──────────────────────────────────────────────────────────────
_MAP_CANONICAL: dict[str, str] = {m.lower(): m for m in ALL_MAP_NAMES}
 
 
# ══════════════════════════════════════════════════════════════════════════════
# CACHE JSON
# ══════════════════════════════════════════════════════════════════════════════
 
def _cache_path(url: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe = re.sub(r"[^\w]", "_", url)[:80]
    return os.path.join(CACHE_DIR, f"{safe}.json")
 
def cache_load(url: str) -> Optional[dict]:
    path = _cache_path(url)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if datetime.now() - datetime.fromisoformat(entry["_cached_at"]) > CACHE_TTL:
            os.remove(path)
            return None
        return entry["data"]
    except Exception:
        return None
 
def cache_save(url: str, data: dict) -> None:
    try:
        with open(_cache_path(url), "w", encoding="utf-8") as f:
            json.dump({"_cached_at": datetime.now().isoformat(), "data": data},
                      f, ensure_ascii=False, indent=2)
    except Exception:
        pass
 
def cache_invalidate(url: str) -> None:
    p = _cache_path(url)
    if os.path.exists(p): os.remove(p)
 
def cache_list() -> list:
    entries = []
    if not os.path.exists(CACHE_DIR):
        return entries
    for fname in os.listdir(CACHE_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(CACHE_DIR, fname), "r", encoding="utf-8") as f:
                entry = json.load(f)
            cached_at = datetime.fromisoformat(entry["_cached_at"])
            age = datetime.now() - cached_at
            entries.append({
                "url":       entry["data"].get("url", fname),
                "team":      entry["data"].get("team_name", "?"),
                "cached_at": cached_at.strftime("%d/%m %H:%M"),
                "age_h":     round(age.total_seconds() / 3600, 1),
                "expired":   age > CACHE_TTL,
            })
        except Exception:
            pass
    return sorted(entries, key=lambda x: x["age_h"])
 
 
# ══════════════════════════════════════════════════════════════════════════════
# HTTP
# ══════════════════════════════════════════════════════════════════════════════
 
def _get(url: str, delay: float = 1.5, retries: int = 3) -> BeautifulSoup:
    for attempt in range(retries):
        try:
            time.sleep(delay + random.uniform(0.2, 0.6))
            resp = requests.get(url, headers=HEADERS, timeout=25)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise ConnectionError(f"Falha ao acessar {url}: {e}")
            time.sleep(2 ** attempt)
 
 
# ══════════════════════════════════════════════════════════════════════════════
# UTILITÁRIOS
# ══════════════════════════════════════════════════════════════════════════════
 
def detect_source(url: str) -> str:
    if "vlr.gg"         in url: return "vlr"
    if "liquipedia.net" in url: return "liquipedia"
    return "unknown"
 
def extract_team_name(url: str) -> str:
    m = re.search(r"/team/\d+/([^/?#]+)", url, re.I)
    if m: return m.group(1).replace("-", " ").title()
    m = re.search(r"/Team/([^/?#]+)", url)
    if m: return m.group(1).replace("_", " ")
    return url.rstrip("/").split("/")[-1].replace("-"," ").replace("_"," ").title()
 
def get_recent_form_from_results(results: list) -> list:
    return [r["result"] for r in results if r.get("result") in ("W", "L")][:10]
 
def _safe_float(val, default: float = 0.0) -> float:
    try:
        cleaned = re.sub(r"[^\d.\-]", "", str(val))
        return float(cleaned) if cleaned else default
    except Exception:
        return default
 
def _normalize_role(raw: str) -> str:
    kw = {
        "duelist":"Duelist","entry":"Duelist","fragger":"Duelist",
        "initiator":"Initiator","support":"Initiator","recon":"Initiator",
        "controller":"Controller","smoker":"Controller",
        "sentinel":"Sentinel","anchor":"Sentinel",
        "igl":"IGL","captain":"IGL","leader":"IGL",
        "coach":"Coach",
    }
    r = raw.lower().strip()
    for key, val in kw.items():
        if key in r: return val
    return "Flex"
 
def _is_non_player(text: str) -> bool:
    """
    Filtro de não-jogadores baseado em HTML real.
    Jogadores ativos têm role VAZIA. Não-jogadores têm:
      'Sub', 'head coach', 'assistant coach', etc.
    """
    t = text.lower().strip()
    return any(tok in t for tok in NON_PLAYER_TOKENS)
 
 
# ══════════════════════════════════════════════════════════════════════════════
# PARSER DA PÁGINA DO PLAYER — stats reais via média ponderada por agente
#
# ESTRUTURA CONFIRMADA COM HTML REAL:
#   table.wf-table  (única tabela na página)
#   headers: '' | Use | RND | Rating2.0 | ACS | K:D | ADR | KAST |
#             KPR | APR | FKPR | FDPR | K | D | A | FK | FD
#   índices:  0     1    2       3      4    5    6     7
#              8    9    10    11    12  13  14  15  16
#
# Cada linha = um agente. Stats gerais = média ponderada por RND.
# ══════════════════════════════════════════════════════════════════════════════
 
def _parse_player_page(soup: BeautifulSoup) -> dict:
    """
    Extrai stats reais de um jogador da página /player/ID/nome do VLR.
 
    Retorna dict com: name, role, top_agents, rating, acs, kda,
    first_kills_per_round, first_deaths_per_round, kills_per_round,
    assists_per_round.
    """
    result = {
        "name": "", "role": "Flex", "top_agents": [],
        "rating": 0.0, "acs": 0.0, "kda": 0.0,
        "first_kills_per_round": 0.0, "first_deaths_per_round": 0.0,
        "kills_per_round": 0.0, "deaths_per_round": 0.0, "assists_per_round": 0.0,
    }
 
    # Nome do player
    h1 = soup.select_one("h1.wf-title")
    if h1:
        result["name"] = h1.get_text(strip=True)
 
    # A única tabela da página: stats por agente
    tbl = soup.select_one("table.wf-table")
    if not tbl:
        return result
 
    rows = tbl.select("tbody tr")
    if not rows:
        return result
 
    total_rnd = 0.0
    w_rating = w_acs = w_kda = w_kpr = w_apr = w_fkpr = w_fdpr = 0.0
    agent_rounds: dict[str, float] = {}
 
    for row in rows:
        tds = row.select("td")
        if len(tds) < 12:
            continue
 
        # Col 0: agente — img[alt]
        img   = tds[0].find("img")
        agent = img.get("alt", "").lower().strip() if img else ""
 
        # Col 2: RND — peso da média ponderada
        rnd = _safe_float(tds[2].get_text(strip=True))
        if rnd <= 0:
            continue
 
        # Colunas confirmadas com HTML real:
        rating = _safe_float(tds[3].get_text(strip=True))   # Rating2.0
        acs    = _safe_float(tds[4].get_text(strip=True))   # ACS
        kda    = _safe_float(tds[5].get_text(strip=True))   # K:D (já calculado pelo VLR)
        kpr    = _safe_float(tds[8].get_text(strip=True))   # KPR
        apr    = _safe_float(tds[9].get_text(strip=True))   # APR
        fkpr   = _safe_float(tds[10].get_text(strip=True))  # FKPR
        fdpr   = _safe_float(tds[11].get_text(strip=True))  # FDPR
 
        # Acumula para média ponderada por RND
        total_rnd += rnd
        w_rating  += rating * rnd
        w_acs     += acs    * rnd
        w_kda     += kda    * rnd
        w_kpr     += kpr    * rnd
        w_apr     += apr    * rnd
        w_fkpr    += fkpr   * rnd
        w_fdpr    += fdpr   * rnd
 
        if agent:
            agent_rounds[agent] = agent_rounds.get(agent, 0) + rnd
 
    if total_rnd > 0:
        result["rating"]                  = round(w_rating / total_rnd, 3)
        result["acs"]                     = round(w_acs    / total_rnd, 1)
        result["kda"]                     = round(w_kda    / total_rnd, 3)
        result["kills_per_round"]         = round(w_kpr    / total_rnd, 4)
        result["assists_per_round"]       = round(w_apr    / total_rnd, 4)
        result["first_kills_per_round"]   = round(w_fkpr   / total_rnd, 4)
        result["first_deaths_per_round"]  = round(w_fdpr   / total_rnd, 4)
 
    # Top 3 agentes por rounds → role
    sorted_agents = sorted(agent_rounds.items(), key=lambda x: x[1], reverse=True)
    result["top_agents"] = [a for a, _ in sorted_agents[:3]]
 
    # Role: só atribui role específica se houver MAIORIA nos top 3
    # Ex: Omen+Jett+Kayo = 1 Controller + 1 Duelist + 1 Initiator → Flex
    # Ex: Omen+Viper+Jett = 2 Controller + 1 Duelist → Controller
    top3_roles = [AGENT_ROLE_MAP[a] for a, _ in sorted_agents[:3] if a in AGENT_ROLE_MAP]
    if top3_roles:
        role_votes = Counter(top3_roles)
        top_role, top_count = role_votes.most_common(1)[0]
        # Exige maioria: pelo menos 2 de 3 (ou todos iguais)
        result["role"] = top_role if top_count >= 2 else "Flex"
    else:
        result["role"] = "Flex"
 
    return result
 
 
def _fetch_player_stats(player_url: str) -> dict:
    """
    Acessa a página do jogador e retorna stats reais.
    Retorna dict vazio em caso de falha (silencioso — usa defaults no models).
    """
    if not player_url or "vlr.gg/player" not in player_url:
        return {}
    try:
        soup = _get(player_url, delay=1.0)
        return _parse_player_page(soup)
    except Exception:
        return {}
 
 
 
# ══════════════════════════════════════════════════════════════════════════════
# PARSER DE STATS POR MAPA — página /team/stats/ID/NOME
#
# Estrutura confirmada com HTML real (debug_stats.html):
#   table.wf-table.mod-team-maps
#   Headers: Map (#) | Expand | WIN% | W | L | ATK1st | DEF1st | ...
#   Linhas de mapa: "Bind (38)" | "" | "53%" | "20" | "18" | ...
#   Sub-linhas de partida: começam com data/adversário — ignoradas
#
# O nome do mapa vem no formato "Bind (38)" — extrai "Bind" e 38 jogos.
# ══════════════════════════════════════════════════════════════════════════════
 
def _parse_map_stats_page(soup: BeautifulSoup) -> list:
    """
    Lê a tabela de /team/stats/ID/NOME e retorna lista de dicts por mapa:
    [{"map_name": "Bind", "wins": 20, "losses": 18, "times_played": 38}, ...]
    """
    map_stats = []
    tbl = soup.select_one("table.wf-table.mod-team-maps, table.mod-team-maps, table.wf-table")
    if not tbl:
        return map_stats
 
    for row in tbl.select("tbody tr"):
        cells = [td.get_text(" ", strip=True).strip() for td in row.select("td")]
        if not cells:
            continue
        # Linha de mapa: primeira célula tem formato "MapName (N)"
        # Sub-linhas de partidas têm datas ou adversários — ignorar
        m = re.match(r"^([A-Z][A-Za-z\s]+?)\s*\((\d+)\)$", cells[0].strip())
        if not m:
            continue
        map_name = m.group(1).strip()
        games    = int(m.group(2))
        # cols: 0=Map(#)  1=Expand  2=WIN%  3=W  4=L
        try:
            wins   = int(cells[3]) if cells[3].isdigit() else 0
            losses = int(cells[4]) if cells[4].isdigit() else 0
        except (IndexError, ValueError):
            wins, losses = 0, 0
 
        if map_name and games > 0:
            map_stats.append({
                "map_name":    map_name,
                "wins":        wins,
                "losses":      losses,
                "times_played": games,
            })
 
    return map_stats
 
 
 
# ══════════════════════════════════════════════════════════════════════════════
# STATS POR MAPA — aba /team/stats/ID/NOME
#
# Estrutura confirmada com HTML real (FURIA, março 2026):
#   table.wf-table.mod-team-maps
#   headers: Map (#) | Expand | WIN% | W | L | ATK1st | DEF1st | ...
#   Linhas de mapa: col 0 = "Nome (N)" ex: "Bind (38)"
#   Sub-linhas (resultados individuais): col 0 vazio — IGNORADAS
#
# URL: /team/stats/ID/nome  (diferente de /team/ID/nome)
# ══════════════════════════════════════════════════════════════════════════════
 
def _build_stats_url(team_url: str) -> Optional[str]:
    """Converte /team/ID/nome → /team/stats/ID/nome."""
    path = team_url.replace(VLR_BASE, "").lstrip("/")
    # Só converte se NÃO já tiver "stats" no path
    m = re.match(r"^team/(\d+)/([^/]+)$", path)
    if not m:
        return None
    return f"{VLR_BASE}/team/stats/{m.group(1)}/{m.group(2)}"
 
 
def _parse_map_stats_table(soup: BeautifulSoup) -> dict:
    """
    Lê a tabela de stats por mapa e retorna:
      dict: map_name_lower → {map_name, wins, losses, times_played}
 
    Ignora sub-linhas (partidas individuais) — só processa linhas com
    formato "Nome (N)" na primeira coluna.
    """
    result: dict = {}
    tbl = soup.select_one("table.wf-table.mod-team-maps, table.wf-table")
    if not tbl:
        return result
 
    for row in tbl.select("tbody tr"):
        tds = row.select("td")
        if not tds:
            continue
        first = tds[0].get_text(strip=True)
        # Linhas de mapa: "Bind (38)", "Haven (50)", etc.
        m = re.match(r"^([A-Za-z ]+?)\s*\((\d+)\)$", first)
        if not m:
            continue
        map_name = m.group(1).strip()
        wins   = int(re.sub(r"\D", "", tds[3].get_text(strip=True)) or 0) if len(tds) > 3 else 0
        losses = int(re.sub(r"\D", "", tds[4].get_text(strip=True)) or 0) if len(tds) > 4 else 0
        if map_name and wins + losses > 0:
            result[map_name.lower()] = {
                "map_name":     map_name,
                "wins":         wins,
                "losses":       losses,
                "times_played": wins + losses,
            }
    return result
 
# ══════════════════════════════════════════════════════════════════════════════
# VLR.gg — PÁGINA DE TIME  /team/ID/NOME
# ══════════════════════════════════════════════════════════════════════════════
 
def _vlr_team(soup: BeautifulSoup, url: str) -> dict:
    data = {
        "source": "vlr", "type": "team", "url": url,
        "team_name": "", "tag": "", "region": "",
        "players": [], "recent_results": [], "map_stats": [],
    }
 
    # ── Nome ──
    for sel in ["h1.wf-title", ".team-header-name h1", "h1"]:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            data["team_name"] = el.get_text(strip=True)
            break
 
    # ── Região ──
    region_el = soup.select_one(".team-header-country, .team-summary-item-value")
    if region_el:
        data["region"] = region_el.get_text(strip=True)
 
    # ── Roster ──
    # Confirmado com HTML real:
    #   - alias em .team-roster-item-name-alias
    #   - role em .team-roster-item-name-role (VAZIA para jogadores, preenchida para staff)
    #   - filtro: _is_non_player(role) cobre todos os casos reais encontrados
    for item in soup.select("div.team-roster-item"):
        alias_el = item.select_one(".team-roster-item-name-alias")
        role_el  = item.select_one(".team-roster-item-name-role")
        link_el  = item.select_one("a[href*='/player/']")
 
        if not alias_el:
            continue
 
        ign      = alias_el.get_text(strip=True)
        role_raw = role_el.get_text(strip=True) if role_el else ""
 
        if not ign:
            continue
 
        # Filtra Sub, head coach, assistant coach, etc.
        # Baseado em HTML real: jogadores têm role="" ou role ausente
        if _is_non_player(role_raw) or _is_non_player(ign):
            continue
 
        href = link_el["href"] if link_el and link_el.get("href") else ""
        purl = (VLR_BASE + href) if href.startswith("/") else href
 
        # Busca stats reais na página individual do player
        # Isso retorna rating, acs, kda, fkpr, fdpr, role e top_agents
        player_stats = _fetch_player_stats(purl)
 
        # Monta dict do player com stats reais (ou zeros se a busca falhou)
        player_entry = {
            "name":       ign,
            "role":       player_stats.get("role", "Flex"),
            "top_agents": player_stats.get("top_agents", []),
            "url":        purl,
            "rating":               player_stats.get("rating", 0.0),
            "acs":                  player_stats.get("acs", 0.0),
            "kda":                  player_stats.get("kda", 0.0),
            "first_kills_per_round":  player_stats.get("first_kills_per_round", 0.0),
            "first_deaths_per_round": player_stats.get("first_deaths_per_round", 0.0),
            "kills_per_round":      player_stats.get("kills_per_round", 0.0),
            "deaths_per_round":     player_stats.get("deaths_per_round", 0.0),
            "assists_per_round":    player_stats.get("assists_per_round", 0.0),
        }
        data["players"].append(player_entry)
 
    # ── Stats por mapa: busca /team/stats/ID/nome ──
    stats_url = _build_stats_url(url)
    if stats_url:
        try:
            stats_soup = _get(stats_url, delay=1.2)
            map_stats_raw = _parse_map_stats_table(stats_soup)
            if map_stats_raw:
                data["map_stats"] = list(map_stats_raw.values())
        except Exception:
            pass   # falha silenciosa — map_stats ficará vazio
 
    # ── Resultados recentes ──
    # Seletor confirmado com HTML real: a.wf-card.m-item (partidas com placar)
    # NÃO usar a.wf-module-item — esses são artigos de notícia sem placar
    for card in soup.select("a.wf-card.m-item"):
        result_el = card.select_one(".m-item-result")
        if not result_el:
            continue
 
        # W/L via classe CSS (mais confiável)
        cls = " ".join(result_el.get("class", []))
        if "mod-win" in cls:
            result = "W"
        elif "mod-loss" in cls:
            result = "L"
        else:
            # Fallback: compara os dois spans do placar (ex: "1 : 2")
            spans = result_el.select("span")
            if len(spans) >= 2:
                try:
                    s1 = int(re.sub(r"\D", "", spans[0].get_text()))
                    s2 = int(re.sub(r"\D", "", spans[1].get_text()))
                    result = "W" if s1 > s2 else "L"
                except Exception:
                    continue
            else:
                continue
 
        # Adversário: .m-item-team-name excluindo o próprio time da página
        opponent = ""
        page_name = data["team_name"].upper()
        for name_el in card.select(".m-item-team-name"):
            name = name_el.get_text(strip=True)
            if name.upper() != page_name:
                opponent = name
                break
 
        # Data e evento
        date_el  = card.select_one(".m-item-date div")
        event_el = card.select_one(".m-item-event .text-of")
 
        if result in ("W", "L") and opponent:
            data["recent_results"].append({
                "result":   result,
                "opponent": opponent,
                "date":     date_el.get_text(strip=True)  if date_el  else "",
                "event":    event_el.get_text(strip=True) if event_el else "",
            })
        if len(data["recent_results"]) >= 10:
            break
 
    # ── Stats por mapa — busca aba /team/stats/ID/NOME ──
    # Essa aba tem W/L real por mapa (ex: Bind: W=20 L=18)
    m_url = re.search(r"/team/(\d+)/(.+)$", url.replace(VLR_BASE, ""))
    if m_url:
        stats_url = f"{VLR_BASE}/team/stats/{m_url.group(1)}/{m_url.group(2)}"
        try:
            stats_soup = _get(stats_url, delay=1.2)
            data["map_stats"] = _parse_map_stats_page(stats_soup)
        except Exception:
            data["map_stats"] = []
    else:
        data["map_stats"] = []
 
    return data
 
 
def _extract_vlr_result(el) -> str:
    for score in el.select(".match-item-vs-team-score"):
        cls = " ".join(score.get("class", []))
        if "mod-win"  in cls: return "W"
        if "mod-loss" in cls: return "L"
    for team in el.select(".match-item-vs-team"):
        cls = " ".join(team.get("class", []))
        if "mod-win"  in cls: return "W"
        if "mod-loss" in cls: return "L"
    scores = el.select(".match-item-vs-team-score")
    if len(scores) >= 2:
        try:
            s = [int(re.sub(r"\D","",x.get_text())) for x in scores]
            right = el.select(".match-item-vs-team.mod-right .match-item-vs-team-score")
            if right:
                rs = int(re.sub(r"\D","",right[0].get_text()))
                ls = s[0] if rs == s[1] else s[1]
                return "W" if rs > ls else "L"
            return "W" if s[0] > s[1] else "L"
        except Exception:
            pass
    return "?"
 
 
# ══════════════════════════════════════════════════════════════════════════════
# VLR.gg — PÁGINA DE PARTIDA  /MATCH_ID/...
# ══════════════════════════════════════════════════════════════════════════════
 
def _vlr_match(soup: BeautifulSoup, url: str) -> dict:
    data = {
        "source":"vlr","type":"match","url":url,
        "teams":[],"maps_played":[],"map_scores":[],"players":{},
    }
    for td in soup.select(".match-header-link-name .wf-title"):
        name = td.get_text(strip=True)
        if name: data["teams"].append({"name": name})
    if len(data["teams"]) < 2:
        title = soup.find("title")
        if title:
            m = re.search(r"(.+?)\s+vs\.?\s+(.+?)(?:\s*[|\-·]|$)", title.get_text(), re.I)
            if m:
                data["teams"] = [{"name":m.group(1).strip()},{"name":m.group(2).strip()}]
    for game in soup.select("div.vm-stats-game"):
        map_el   = game.select_one(".map div:not(.mod-sq)") or game.select_one(".map")
        map_name = re.sub(r"\b(PICK|BAN|TBD|SKIPPED)\b","",
                          map_el.get_text(strip=True) if map_el else "",flags=re.I).strip()
        if not map_name or map_name.lower() in ("all",""):
            continue
        data["maps_played"].append(map_name)
        data["map_scores"].append([s.get_text(strip=True) for s in game.select(".score")][:2])
        for row in game.select("tbody tr"):
            name_el = row.select_one(".text-of")
            if not name_el: continue
            pname = name_el.get_text(strip=True)
            tds   = row.select("td")
            def td(i,d="0"):
                try:    return tds[i].get_text(strip=True).split("\n")[0].strip()
                except: return d
            if pname not in data["players"]:
                data["players"][pname] = {"name":pname,"maps_data":[]}
            data["players"][pname]["maps_data"].append({
                "map":map_name,"rating":_safe_float(td(1)),"acs":_safe_float(td(2)),
                "kills":_safe_float(td(3)),"deaths":_safe_float(td(4)),
                "fk":_safe_float(td(9)),"fd":_safe_float(td(10)),
            })
    return data
 
 
# ══════════════════════════════════════════════════════════════════════════════
# LIQUIPEDIA
# ══════════════════════════════════════════════════════════════════════════════
 
def _lp_team(soup: BeautifulSoup, url: str) -> dict:
    data = {
        "source":"liquipedia","type":"team","url":url,
        "team_name":"","players":[],"recent_results":[],
    }
    h1 = soup.find("h1", id="firstHeading")
    data["team_name"] = h1.get_text(strip=True) if h1 else extract_team_name(url)
    roster = soup.find("table", class_=re.compile(r"roster", re.I))
    if roster:
        for row in roster.select("tr"):
            cells = row.select("td")
            if len(cells) < 2: continue
            link = cells[1].select_one("a[href*='/Player/']")
            if not link: continue
            ign      = link.get_text(strip=True)
            role_raw = cells[0].get_text(strip=True)
            if _is_non_player(role_raw) or _is_non_player(ign):
                continue
            data["players"].append({
                "name":ign,"role":_normalize_role(role_raw),
                "top_agents":[],"url":LIQUIPEDIA_BASE+link["href"],
                "rating":0.0,"acs":0.0,"kda":0.0,
                "first_kills_per_round":0.0,"first_deaths_per_round":0.0,
            })
    return data
 
def _lp_match(soup: BeautifulSoup, url: str) -> dict:
    data = {"source":"liquipedia","type":"match","url":url,"teams":[],"maps":[]}
    for box in soup.select(".team-left, .team-right"):
        el = box.select_one(".team-template-text a")
        if el: data["teams"].append({"name":el.get_text(strip=True)})
    if len(data["teams"]) < 2:
        h1 = soup.find("h1", id="firstHeading")
        if h1:
            m = re.search(r"(.+?)\s+vs\.?\s+(.+)", h1.get_text(strip=True), re.I)
            if m:
                data["teams"] = [{"name":m.group(1).strip()},{"name":m.group(2).strip()}]
    for row in soup.select(".mapveto-map, td.map"):
        name = row.get_text(strip=True)
        if name and len(name) > 2: data["maps"].append(name)
    return data
 
 
# ══════════════════════════════════════════════════════════════════════════════
# INTERFACE PÚBLICA
# ══════════════════════════════════════════════════════════════════════════════
 
def scrape_url(url: str, force_refresh: bool = False) -> dict:
    """
    Detecta fonte (VLR/Liquipedia), verifica cache, faz scraping se necessário.
    Para times VLR, acessa a página de cada player para obter stats reais.
    """
    url    = url.strip().rstrip("/")
    source = detect_source(url)
    if source == "unknown":
        raise ValueError(f"URL não suportada. Use VLR.gg ou Liquipedia.\nURL: {url}")
 
    if not force_refresh:
        cached = cache_load(url)
        if cached is not None:
            cached["_from_cache"] = True
            return cached
 
    delay  = 1.0 if source == "vlr" else 2.5
    soup   = _get(url, delay=delay)
 
    if source == "vlr":
        path   = url.replace(VLR_BASE, "").lstrip("/")
        result = _vlr_team(soup, url) if path.startswith("team/") else _vlr_match(soup, url)
    else:
        result = _lp_team(soup, url) if "/Team/" in url else _lp_match(soup, url)
 
    result["_from_cache"] = False
    cache_save(url, result)
    return result
 
 
# ══════════════════════════════════════════════════════════════════════════════
# MAP POOL DINÂMICO
# ══════════════════════════════════════════════════════════════════════════════
 
def fetch_active_map_pool() -> list:
    """
    Raspa vlr.gg/matches/results e detecta mapas do pool ativo.
    Valida contra _MAP_CANONICAL (12 mapas canônicos).
    Fallback: vct-2025.
    """
    try:
        soup = _get("https://www.vlr.gg/matches/results", delay=1.0)
        counter: dict = {}
        for el in soup.select("[class*='map'], .map-name"):
            text      = el.get_text(strip=True).lower().strip()
            canonical = _MAP_CANONICAL.get(text)
            if canonical:
                counter[canonical] = counter.get(canonical, 0) + 1
        active = [m for m, c in counter.items() if c >= 2]
        if len(active) >= 5:
            return sorted(active)
    except Exception:
        pass
    return MAP_POOL_HISTORY["vct-2025"]
 