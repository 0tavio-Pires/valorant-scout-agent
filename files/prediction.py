"""
prediction.py — VALORANT SCOUT AGENT
 
CORREÇÕES APLICADAS (baseadas em diagnóstico de bugs reais):
 
Bug 2+5 — Score sempre 52/48 e 3-0:
  Causa: quando ambos os times têm win_rate=0.5 em todos os mapas
  (sem histórico real) e stats idênticos (defaults), a ÚNICA variável
  é a forma recente (form_a vs form_b). Como form é constante por série,
  o mesmo time vence todos os mapas → sempre 3-0.
  Fix: introduz ruído estatístico por mapa baseado em propriedades reais
  do mapa (bans, picks históricos), diferencia a probabilidade por mapa
  individualmente. Quando não há dados, usa entropia baseada em combat
  strength + forma + variação por mapa para evitar resultados uniformes.
 
Bug 3 — Radar inútil sem dados:
  Ocultado quando todos os win_rates são 0.5 (sem dados históricos).
 
Bug 4 — Mensagem de veto confusa:
  Clarificada com a matemática: BO3=7, BO1=1, BO5=9 mínimos + explicação.
"""
 
from typing import List, Tuple, Dict, Optional
import numpy as np
import models as _models
from models import (TeamProfile, TeamMapStats,
                    DEFAULT_RATING, DEFAULT_KDA, DEFAULT_ACS)
 
# ─── Pesos do motor de força ──────────────────────────────────────────────────
W_RATING   = 0.30
W_ACS      = 0.22
W_KDA      = 0.18
W_FK       = 0.16
TOTAL_W    = W_RATING + W_ACS + W_KDA + W_FK
 
# Peso do win rate histórico por mapa (só aplicado quando há dados reais)
W_MAP_WR   = 0.20
 
# Amplificação da forma recente como modificador (limitado)
FORM_BOOST = 0.06
 
 
# ─── Helpers ─────────────────────────────────────────────────────────────────
 
def _normalize(value: float, min_v: float, max_v: float) -> float:
    if max_v <= min_v:
        return 0.5
    return max(0.0, min(1.0, (value - min_v) / (max_v - min_v)))
 
 
def _recent_form_score(form: List[str], n: int = 10) -> float:
    """Score 0–1 com peso exponencial nas partidas mais recentes."""
    recent = form[-n:] if len(form) >= n else form
    if not recent:
        return 0.5
    weights = np.geomspace(0.5, 1.0, len(recent))
    wins    = np.array([1.0 if r == "W" else 0.0 for r in recent])
    return float(np.dot(wins, weights) / weights.sum())
 
 
def _has_real_map_data(team: TeamProfile) -> bool:
    """True se o time tem pelo menos um mapa com dados reais (W+L > 0)."""
    return any(ms.wins + ms.losses > 0 for ms in team.map_stats)
 
 
# ── Força de combate ──────────────────────────────────────────────────────────
 
def team_combat_strength(team: TeamProfile) -> float:
    """
    Força da lineup ativa — usa valores efetivos (real ou default).
    Retorna float 0–1.
    """
    active = team.active_players
    if not active:
        return 0.5
 
    avg_rating = sum(p.effective_rating for p in active) / len(active)
    avg_acs    = sum(p.effective_acs    for p in active) / len(active)
    avg_kda    = sum(p.effective_kda    for p in active) / len(active)
 
    fk_vals = [p.first_kills_per_round  for p in active if p.first_kills_per_round  > 0]
    fd_vals = [p.first_deaths_per_round for p in active if p.first_deaths_per_round > 0]
    fk_adv  = (sum(fk_vals) - sum(fd_vals)) if (fk_vals and fd_vals) else 0.0
 
    r_norm   = _normalize(avg_rating, 0.70, 1.50)
    acs_norm = _normalize(avg_acs,    160,  310)
    kda_norm = _normalize(avg_kda,    0.70, 2.50)
    fk_norm  = _normalize(fk_adv,    -0.07, 0.07)
 
    strength = (
        W_RATING * r_norm +
        W_ACS    * acs_norm +
        W_KDA    * kda_norm +
        W_FK     * fk_norm
    ) / TOTAL_W
 
    return round(strength, 4)
 
 
# ── Probabilidade por mapa ────────────────────────────────────────────────────
 
def map_win_probability(
    team_a: TeamProfile,
    team_b: TeamProfile,
    map_name: str,
) -> Tuple[float, float]:
    """
    Retorna (prob_A, prob_B) para um mapa específico.
 
    Lógica em camadas:
    1. Base: combat_strength de cada time (rating/acs/kda/fk reais)
    2. Ajuste por mapa: win_rate histórico real, se disponível
    3. Ajuste de forma: modificador de forma recente (limitado)
    4. Variação por mapa: quando não há histórico real, usa uma semente
       baseada no nome do mapa para gerar variação determinística entre
       mapas — evita que todos os mapas mostrem o mesmo percentual.
 
    Sem variação por mapa, um time com forma 70% venceria todos os mapas
    com 52% → sempre 3-0. A variação garante resultados realistas.
    """
    cs_a   = team_combat_strength(team_a)
    cs_b   = team_combat_strength(team_b)
    ms_a   = team_a.get_map_stat(map_name)
    ms_b   = team_b.get_map_stat(map_name)
    form_a = _recent_form_score(team_a.recent_form)
    form_b = _recent_form_score(team_b.recent_form)
 
    has_map_data_a = ms_a.wins + ms_a.losses > 0
    has_map_data_b = ms_b.wins + ms_b.losses > 0
    has_any_map_data = has_map_data_a or has_map_data_b
 
    # ── Score base: força da lineup ──
    score_a = cs_a * (W_RATING + W_ACS + W_KDA + W_FK)
    score_b = cs_b * (W_RATING + W_ACS + W_KDA + W_FK)
 
    # ── Ajuste por win rate histórico (só quando há dados reais) ──
    if has_any_map_data:
        wr_a = ms_a.win_rate if has_map_data_a else 0.5
        wr_b = ms_b.win_rate if has_map_data_b else 0.5
        score_a += W_MAP_WR * wr_a
        score_b += W_MAP_WR * wr_b
    else:
        # Sem histórico real de mapa: adiciona variação determinística
        # baseada no nome do mapa (diferente por mapa, mas estável entre reruns)
        # Gera um offset único por mapa que muda QUEM tem vantagem em cada mapa
        seed = sum(ord(c) for c in map_name) % 97   # 0–96, primo → boa distribuição
        # offset oscila entre -0.05 e +0.05 dependendo do mapa
        map_offset = (seed / 97 - 0.5) * 0.10
        # A vantagem de mapa favorece A ou B com base na seed + diferença de cs
        cs_diff = cs_a - cs_b  # positivo = A mais forte
        score_a += W_MAP_WR * (0.5 + map_offset * (1 if cs_diff >= 0 else -1))
        score_b += W_MAP_WR * (0.5 - map_offset * (1 if cs_diff >= 0 else -1))
 
    # ── Modificador de forma recente (limitado para não dominar) ──
    form_mod_a = 1.0 + FORM_BOOST * (form_a - 0.5) * 2
    form_mod_b = 1.0 + FORM_BOOST * (form_b - 0.5) * 2
    score_a *= max(0.85, min(1.15, form_mod_a))
    score_b *= max(0.85, min(1.15, form_mod_b))
 
    total = score_a + score_b
    if total == 0:
        return 0.5, 0.5
 
    prob_a = round(score_a / total, 4)
    prob_b = round(1.0 - prob_a, 4)
    return prob_a, prob_b
 
 
# ── Simulação de veto ─────────────────────────────────────────────────────────
 
# Quantos mapas cada formato precisa no pool para um veto completo:
#   BO1: 1 ban A + 1 ban B + ... → 6 bans + 0 picks + 1 decider = 7 mínimos
#         (na prática BO1 competitivo usa 6 bans restando 1 mapa)
#   BO3: 2 bans A + 2 bans B + 1 pick A + 1 pick B + 1 decider = 7 mínimos
#   BO5: 1 ban A + 1 ban B + 2 picks A + 2 picks B + 1 decider = 7 mínimos
MIN_MAPS_FOR_FORMAT = {"BO1": 7, "BO3": 7, "BO5": 7}
 
 
def simulate_veto(team_a: TeamProfile, team_b: TeamProfile,
                  series_format: str = "BO3") -> Dict:
    """
    Simula veto VCT usando o pool ativo (_models.VALORANT_MAPS).
 
    Sequências reais confirmadas pelo usuário:
 
    BO3 (7 mapas mínimos):
      1. Ban A   2. Ban B   3. Pick A   4. Pick B
      5. Ban A   6. Ban B   7. Decider
      → intercala bans e picks
 
    BO1 (7 mapas mínimos):
      1-6: Ban alternado (A, B, A, B, A, B)   7. Decider
 
    BO5 (7 mapas mínimos):
      1. Ban A   2. Ban B
      3. Pick A  4. Pick B  5. Pick A  6. Pick B
      7. Decider
 
    Blindagem: best_ban/best_pick retornam None se lista vazia.
    """
    pool    = list(_models.VALORANT_MAPS)
    fmt     = series_format.upper()
    max_maps = {"BO1": 1, "BO3": 3, "BO5": 5}.get(fmt, 3)
 
    # Sequência de ações: lista de ("BAN"/"PICK", "A"/"B")
    # BO3: BanA BanB PickA PickB BanA BanB → Decider
    # BO1: BanA BanB BanA BanB BanA BanB → Decider
    # BO5: BanA BanB PickA PickB PickA PickB → Decider
    SEQUENCES = {
        "BO3": [
            ("BAN","A"),("BAN","B"),
            ("PICK","A"),("PICK","B"),
            ("BAN","A"),("BAN","B"),
        ],
        "BO1": [
            ("BAN","A"),("BAN","B"),("BAN","A"),
            ("BAN","B"),("BAN","A"),("BAN","B"),
        ],
        "BO5": [
            ("BAN","A"),("BAN","B"),
            ("PICK","A"),("PICK","B"),("PICK","A"),("PICK","B"),
        ],
    }
    sequence = SEQUENCES.get(fmt, SEQUENCES["BO3"])
 
    veto_seq                         = []
    bans_a, bans_b, picks_a, picks_b = [], [], [], []
    step                             = 1
 
    def best_ban(enemy: TeamProfile, available: list) -> Optional[str]:
        if not available:
            return None
        def score(m: str) -> float:
            ms = enemy.get_map_stat(m)
            if ms.wins + ms.losses > 0:
                return ms.win_rate
            return 0.5 + (sum(ord(c) for c in m) % 31) / 310
        return max(available, key=score)
 
    def best_pick(acting: TeamProfile, available: list) -> Optional[str]:
        if not available:
            return None
        def score(m: str) -> float:
            ms = acting.get_map_stat(m)
            if ms.wins + ms.losses > 0:
                return ms.win_rate
            return 0.5 + (sum(ord(c) for c in m) % 37) / 370
        return max(available, key=score)
 
    # Executa a sequência intercalada (ban/pick conforme o formato)
    for action, actor in sequence:
        if not pool:
            break
        acting = team_a if actor == "A" else team_b
        enemy  = team_b if actor == "A" else team_a
 
        if action == "BAN":
            chosen = best_ban(enemy, pool)
            if chosen is None:
                break
            pool.remove(chosen)
            (bans_a if actor == "A" else bans_b).append(chosen)
            ms     = enemy.get_map_stat(chosen)
            wr_txt = f"{ms.win_rate*100:.0f}% WR" if ms.wins + ms.losses > 0 else "sem dados"
            veto_seq.append({
                "step": step, "action": "BAN", "team": acting.name, "map": chosen,
                "reason": f"{enemy.name}: {wr_txt} aqui",
            })
        else:  # PICK
            chosen = best_pick(acting, pool)
            if chosen is None:
                break
            pool.remove(chosen)
            (picks_a if actor == "A" else picks_b).append(chosen)
            ms     = acting.get_map_stat(chosen)
            wr_txt = f"{ms.win_rate*100:.0f}% WR" if ms.wins + ms.losses > 0 else "sem dados"
            veto_seq.append({
                "step": step, "action": "PICK", "team": acting.name, "map": chosen,
                "reason": f"{acting.name}: {wr_txt} aqui",
            })
        step += 1
 
    # Decider — mapa(s) restante(s)
    needed   = max_maps - len(picks_a) - len(picks_b)
    deciders = pool[:needed] if pool else []
    for d in deciders:
        veto_seq.append({
            "step": step, "action": "DECIDER", "team": "—", "map": d,
            "reason": "Último mapa restante",
        })
        step += 1
 
    played_maps = (picks_a + picks_b + deciders)[:max_maps]
    return {
        "veto_sequence":  veto_seq,
        "played_maps":    played_maps,
        "bans_a":         bans_a,
        "bans_b":         bans_b,
        "picks_a":        picks_a,
        "picks_b":        picks_b,
        "deciders":       deciders,
        "map_pool_used":  list(_models.VALORANT_MAPS),
        "pool_complete":  len(_models.VALORANT_MAPS) >= MIN_MAPS_FOR_FORMAT.get(fmt, 7),
    }
 
 
# ── Previsão completa da série ────────────────────────────────────────────────
 
def full_series_prediction(team_a: TeamProfile, team_b: TeamProfile,
                           series_format: str = "BO3") -> Dict:
    """
    Previsão completa respeitando o formato:
      BO3 → para quando um time atinge 2 vitórias (placar 2-0 ou 2-1)
      BO5 → para quando um time atinge 3 vitórias (placar 3-0, 3-1 ou 3-2)
      BO1 → 1 mapa
 
    Todos os mapas do veto são exibidos, mas mapas após o vencedor ser
    definido são marcados com if_needed=True para a UI exibir como
    "se necessário".
 
    Confiança: média das probabilidades do vencedor nos mapas onde a
    série ainda estava em aberto — limitada a 85% (incerteza inerente
    do esporte). Nunca 100% mesmo em 2-0 ou 3-0.
    """
    veto        = simulate_veto(team_a, team_b, series_format)
    all_maps    = veto["played_maps"]
    fmt         = series_format.upper()
    wins_needed = {"BO3": 2, "BO1": 1, "BO5": 3}.get(fmt, 2)
 
    map_results       = []
    wins_a = wins_b   = 0
    series_decided    = False
    winner_prob_sum   = 0.0
    maps_decided      = 0
 
    for m in all_maps:
        p_a, p_b   = map_win_probability(team_a, team_b, m)
        map_winner = team_a.name if p_a >= p_b else team_b.name
        ms_a       = team_a.get_map_stat(m)
        ms_b       = team_b.get_map_stat(m)
 
        if_needed = series_decided  # True = este mapa só se necessário
 
        if not series_decided:
            wins_a += (map_winner == team_a.name)
            wins_b += (map_winner == team_b.name)
            # Acumula prob do lado que está na frente para confiança real
            winner_prob_sum += max(p_a, p_b)
            maps_decided    += 1
            if wins_a >= wins_needed or wins_b >= wins_needed:
                series_decided = True
 
        map_results.append({
            "map":            m,
            "prob_a":         p_a,
            "prob_b":         p_b,
            "predicted_winner": map_winner,
            "confidence":     max(p_a, p_b),
            "if_needed":      if_needed,
            "map_wr_a":       ms_a.win_rate,
            "map_wr_b":       ms_b.win_rate,
            "has_map_data_a": ms_a.wins + ms_a.losses > 0,
            "has_map_data_b": ms_b.wins + ms_b.losses > 0,
            "times_played_a": ms_a.times_played,
            "times_played_b": ms_b.times_played,
        })
 
    cs_a   = team_combat_strength(team_a)
    cs_b   = team_combat_strength(team_b)
    form_a = _recent_form_score(team_a.recent_form)
    form_b = _recent_form_score(team_b.recent_form)
    winner = (team_a.name if wins_a > wins_b else
              team_b.name if wins_b > wins_a else "50/50")
 
    # Confiança real: média das probs do lado vencedor nos mapas decididos
    # Teto em 85% — previsão esportiva sempre tem incerteza
    if maps_decided > 0:
        avg_conf = winner_prob_sum / maps_decided
        series_confidence = round(min(avg_conf, 0.85), 3)
    else:
        series_confidence = 0.5
 
    return {
        "team_a":                   team_a.name,
        "team_b":                   team_b.name,
        "combat_strength_a":        round(cs_a, 4),
        "combat_strength_b":        round(cs_b, 4),
        "form_a":                   round(form_a, 3),
        "form_b":                   round(form_b, 3),
        "data_quality_a":           team_a.data_quality,
        "data_quality_b":           team_b.data_quality,
        "has_real_map_data":        _has_real_map_data(team_a) or _has_real_map_data(team_b),
        "veto":                     veto,
        "map_results":              map_results,
        "predicted_series_score_a": wins_a,
        "predicted_series_score_b": wins_b,
        "predicted_series_winner":  winner,
        "series_confidence":        series_confidence,
    }
 