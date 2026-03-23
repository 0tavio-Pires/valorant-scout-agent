"""
models.py — VALORANT SCOUT AGENT
Modelos de dados puros. Toda informação vem do scraper em runtime.
"""

from dataclasses import dataclass, field
from typing import List

# ─── Base global de mapas (12 mapas) com localizações exatas ─────────────────
ALL_MAPS: dict[str, str] = {
    "Abyss":    "Noruega",
    "Ascent":   "Itália",
    "Bind":     "Marrocos",
    "Breeze":   "Atlântico",
    "Corrode":  "França",
    "Fracture": "EUA",
    "Haven":    "Butão",
    "Icebox":   "Rússia",
    "Lotus":    "Índia",
    "Pearl":    "Portugal",
    "Split":    "Japão",
    "Sunset":   "EUA",
}
# "Neon City" não existe nesta base — removido definitivamente.

ALL_MAP_NAMES: List[str] = sorted(ALL_MAPS.keys())   # lista canônica ordenada

# ─── Pools históricos ─────────────────────────────────────────────────────────
MAP_POOL_HISTORY: dict[str, List[str]] = {
    "vct-2025":   ["Abyss", "Ascent", "Bind", "Haven", "Lotus", "Pearl",
                   "Split", "Sunset", "Corrode"],
    "vct-2024-3": ["Abyss", "Ascent", "Bind", "Haven", "Icebox",
                   "Lotus", "Split", "Sunset"],
    "vct-2024":   ["Abyss", "Ascent", "Bind", "Icebox", "Lotus",
                   "Pearl", "Split", "Sunset"],
}

# Pool ativo — sobrescrito em runtime pelo app via multiselect ou scraper
CURRENT_MAP_POOL: List[str] = MAP_POOL_HISTORY["vct-2025"]
VALORANT_MAPS:    List[str] = CURRENT_MAP_POOL   # referência mutável

# ─── Defaults para fallback quando stats não estão disponíveis ────────────────
DEFAULT_RATING: float = 1.0
DEFAULT_KDA:    float = 1.0
DEFAULT_ACS:    float = 210.0


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class PlayerStats:
    name: str
    role: str                      = "Flex"
    # KPIs — 0.0 significa "não disponível via scraping"
    rating:                 float  = 0.0
    kda:                    float  = 0.0
    kills_per_round:        float  = 0.0
    deaths_per_round:       float  = 0.0
    assists_per_round:      float  = 0.0
    first_kills_per_round:  float  = 0.0
    first_deaths_per_round: float  = 0.0
    acs:                    float  = 0.0
    clutch_rate:            float  = 0.0
    maps_played:            int    = 0
    win_rate:               float  = 0.0
    top_agents:             List[str] = field(default_factory=list)
    preferred_maps:         List[str] = field(default_factory=list)

    @property
    def has_real_stats(self) -> bool:
        """True se veio com pelo menos um KPI real do scraper."""
        return self.rating > 0 or self.acs > 0 or self.kda > 0

    # ── Valores efetivos: real quando disponível, default quando não ──────────
    @property
    def effective_rating(self) -> float:
        return self.rating if self.rating > 0 else DEFAULT_RATING

    @property
    def effective_kda(self) -> float:
        return self.kda if self.kda > 0 else DEFAULT_KDA

    @property
    def effective_acs(self) -> float:
        return self.acs if self.acs > 0 else DEFAULT_ACS


@dataclass
class TeamMapStats:
    map_name:        str
    wins:            int   = 0
    losses:          int   = 0
    times_picked:    int   = 0
    times_banned:    int   = 0
    times_played:    int   = 0
    avg_rounds_won:  float = 0.0
    avg_rounds_lost: float = 0.0

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return self.wins / total if total > 0 else 0.5

    @property
    def pick_rate(self) -> float:
        total = self.times_picked + self.times_banned + 1
        return self.times_picked / total

    @property
    def ban_rate(self) -> float:
        total = self.times_picked + self.times_banned + 1
        return self.times_banned / total


@dataclass
class TeamProfile:
    name:          str
    tag:           str = ""
    region:        str = ""
    source_url:    str = ""
    scraped_at:    str = ""
    players:       List[PlayerStats]   = field(default_factory=list)
    map_stats:     List[TeamMapStats]  = field(default_factory=list)
    recent_wins:   int                 = 0
    recent_losses: int                 = 0
    recent_form:   List[str]           = field(default_factory=list)

    @property
    def active_players(self) -> List[PlayerStats]:
        """Players com stats reais; fallback: todos (com effective defaults)."""
        real = [p for p in self.players if p.has_real_stats]
        return real if real else self.players

    @property
    def avg_rating(self) -> float:
        ps = self.active_players
        return sum(p.effective_rating for p in ps) / len(ps) if ps else DEFAULT_RATING

    @property
    def avg_acs(self) -> float:
        ps = self.active_players
        return sum(p.effective_acs for p in ps) / len(ps) if ps else DEFAULT_ACS

    @property
    def avg_kda(self) -> float:
        ps = self.active_players
        return sum(p.effective_kda for p in ps) / len(ps) if ps else DEFAULT_KDA

    @property
    def fk_advantage(self) -> float:
        ps = self.active_players
        if not ps:
            return 0.0
        return (sum(p.first_kills_per_round for p in ps)
                - sum(p.first_deaths_per_round for p in ps))

    @property
    def win_rate(self) -> float:
        total = self.recent_wins + self.recent_losses
        return self.recent_wins / total if total > 0 else 0.5

    @property
    def data_quality(self) -> str:
        real  = sum(1 for p in self.players if p.has_real_stats)
        total = len(self.players)
        if total == 0:    return "❌ Sem dados"
        pct = real / total
        if pct >= 0.8:    return "✅ Dados reais"
        if pct >= 0.4:    return "⚠️ Dados parciais"
        return "⚠️ Stats indisponíveis (usando defaults)"

    def get_map_stat(self, map_name: str) -> TeamMapStats:
        for ms in self.map_stats:
            if ms.map_name.lower() == map_name.lower():
                return ms
        return TeamMapStats(map_name=map_name)
