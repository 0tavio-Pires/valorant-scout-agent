"""
app.py — VALORANT SCOUT AGENT
Dashboard Streamlit — dados reais via scraping, pool híbrido gerenciado pelo usuário.
"""
 
import sys, os
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
 
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime
import re
 
import models as _m
from models import (
    TeamProfile, PlayerStats, TeamMapStats,
    ALL_MAP_NAMES, ALL_MAPS, MAP_POOL_HISTORY,
)
from prediction import full_series_prediction, team_combat_strength
from scraper import (
    scrape_url, extract_team_name, get_recent_form_from_results,
    detect_source, fetch_active_map_pool, MAP_POOL_HISTORY,
    cache_load, cache_list, cache_invalidate, CACHE_DIR,
)
 
# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="VALORANT SCOUT AGENT",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)
 
# ─── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
 
.vsa-header {
    background: linear-gradient(135deg,#ff4655 0%,#c8102e 50%,#1a1a2e 100%);
    padding:1.8rem 2.5rem; border-radius:12px; margin-bottom:1.5rem;
    border:1px solid #ff4655;
}
.vsa-header h1 { color:#fff; font-size:2.2rem; font-weight:900;
    letter-spacing:2px; margin:0; text-shadow:0 0 20px rgba(255,70,85,0.6); }
.vsa-header p  { color:#aaa; margin:0.3rem 0 0; font-size:0.9rem; }
 
.kpi-card { background:#161b22; border:1px solid #21262d; border-radius:8px;
    padding:0.75rem 1rem; text-align:center; }
.kpi-label { font-size:0.68rem; color:#8b949e; text-transform:uppercase; letter-spacing:1px; }
.kpi-value { font-size:1.3rem; font-weight:700; color:#f0f0f0; }
 
.map-card  { border-radius:8px; padding:0.9rem 1.1rem; margin:0.4rem 0; border-left:4px solid; }
.map-a     { background:rgba(255,70,85,0.07);  border-color:#ff4655; }
.map-b     { background:rgba(0,191,255,0.07);  border-color:#00bfff; }
.map-eq    { background:rgba(255,200,0,0.07);  border-color:#ffc800; }
 
.veto-badge { display:inline-block; padding:2px 8px; border-radius:4px;
    font-size:0.73rem; font-weight:600; margin-right:5px; }
.b-ban     { background:#c8102e22; color:#ff4655; border:1px solid #ff4655; }
.b-pick    { background:#00bfff22; color:#00bfff; border:1px solid #00bfff; }
.b-decider { background:#ffc80022; color:#ffc800; border:1px solid #ffc800; }
 
.winner-box { background:linear-gradient(90deg,#1a1a2e,#ff465518,#1a1a2e);
    border:1px solid #ff4655; border-radius:10px; padding:1.4rem;
    text-align:center; margin:1rem 0; }
 
.role-tag { font-size:0.62rem; font-weight:700; padding:1px 6px;
    border-radius:3px; margin-left:7px; text-transform:uppercase; }
.r-Duelist    { background:#ff465522; color:#ff4655; border:1px solid #ff4655; }
.r-Initiator  { background:#00bfff22; color:#00bfff; border:1px solid #00bfff; }
.r-Controller { background:#9d4edd22; color:#c77dff; border:1px solid #9d4edd; }
.r-Sentinel   { background:#2dce8922; color:#2dce89; border:1px solid #2dce89; }
.r-IGL, .r-Flex, .r-Coach { background:#ffc80022; color:#ffc800; border:1px solid #ffc800; }
 
.stTabs [data-baseweb="tab"]   { background:#161b22!important; color:#8b949e!important;
    border-radius:8px 8px 0 0!important; }
.stTabs [aria-selected="true"] { background:#ff4655!important; color:#fff!important; }
</style>
""", unsafe_allow_html=True)
 
st.markdown("""
<div class="vsa-header">
    <h1>🎯 VALORANT SCOUT AGENT</h1>
    <p>Dados reais · VLR.gg &amp; Liquipedia · Stats via /team/stats · Lineup-based · Cache 24h</p>
</div>
""", unsafe_allow_html=True)
 
 
# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### ⚙️ Configuração")
    st.markdown("---")
 
    series_format = st.selectbox("Formato da série", ["BO3", "BO1", "BO5"], index=0)
 
    # ── Pool de Mapas Ativo — gestão híbrida ─────────────────────────────────
    st.markdown("---")
    st.markdown("**🗺️ Pool de Mapas Ativo**")
    st.caption("Pré-preenchido pelo VLR. Edite livremente com os 12 mapas disponíveis.")
 
    # Busca sugestão do scraper uma vez por sessão
    if "scraper_suggestion" not in st.session_state:
        with st.spinner("🌐 Detectando pool ativo..."):
            try:
                suggestion = fetch_active_map_pool()
                if len(suggestion) < 5:
                    suggestion = MAP_POOL_HISTORY["vct-2025"]
            except Exception:
                suggestion = MAP_POOL_HISTORY["vct-2025"]
            st.session_state["scraper_suggestion"] = suggestion
 
    suggestion = st.session_state["scraper_suggestion"]
 
    # Multiselect com os 12 mapas canônicos — pré-preenchido pela sugestão do VLR
    active_pool = st.multiselect(
        "Mapas no pool",
        options=ALL_MAP_NAMES,
        default=st.session_state.get("active_pool_selection", suggestion),
        key="active_pool_selection",
        format_func=lambda m: f"{m}  ({ALL_MAPS.get(m, '')})",
        help="Sugestão automática do VLR. Adicione ou remova conforme a rotação real.",
    )
 
    # ── Aviso de pool insuficiente — com explicação da matemática do veto ──
    # BO3 = 4 bans + 2 picks + 1 decider = 7 mapas mínimos no pool
    # BO1 = 6 bans + 1 decider           = 7 mapas mínimos no pool
    # BO5 = 2 bans + 4 picks + 1 decider = 7 mapas mínimos no pool
    min_maps = 7  # todos os formatos precisam de 7 mapas no pool
    if len(active_pool) < min_maps:
        fmt_math = {
            "BO3": "4 bans + 2 picks + 1 decider",
            "BO1": "6 bans + 1 decider",
            "BO5": "2 bans + 4 picks + 1 decider",
        }.get(series_format.upper(), "4 bans + 2 picks + 1 decider")
        st.warning(
            f"⚠️ Pool com **{len(active_pool)} mapas** — mínimo necessário: **7**. "
            f"{series_format}: {fmt_math} = 7 mapas. "
            f"Adicione mapas ao pool acima ou o veto ficará incompleto."
        )
 
    if len(active_pool) < 1:
        active_pool = suggestion   # fallback mínimo
 
    # Injeta no módulo para que prediction.py use o pool correto
    _m.VALORANT_MAPS    = active_pool
    _m.CURRENT_MAP_POOL = active_pool
 
    st.caption(f"{len(active_pool)}/7 mapas mínimos necessários para veto completo")
 
    if st.button("🔄 Re-detectar pool do VLR", use_container_width=True):
        st.session_state.pop("scraper_suggestion", None)
        st.rerun()
 
    # ── Cache ─────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("**💾 Cache local**")
    entries = cache_list()
    if entries:
        for e in entries:
            icon = "🟢" if not e["expired"] else "🔴"
            st.markdown(f"{icon} `{e['team']}` — {e['age_h']}h atrás")
        if st.button("🗑️ Limpar cache", use_container_width=True):
            import shutil
            if os.path.exists(CACHE_DIR):
                shutil.rmtree(CACHE_DIR)
            st.session_state.pop("scraper_suggestion", None)
            st.rerun()
    else:
        st.caption("Cache vazio.")
 
    st.markdown("---")
    st.markdown("""
    <div style='font-size:0.72rem;color:#555;line-height:1.7;'>
    📌 URLs aceitas:<br>
    <code>vlr.gg/team/ID/nome</code><br>
    <code>liquipedia.net/valorant/Team/Nome</code><br><br>
    ⚠️ Uso educacional apenas.
    </div>
    """, unsafe_allow_html=True)
 
 
# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════
 
def _kpi(label: str, value: str) -> str:
    return (f"<div class='kpi-card'>"
            f"<div class='kpi-label'>{label}</div>"
            f"<div class='kpi-value'>{value}</div></div>")
 
def _role_tag(role: str) -> str:
    return f"<span class='role-tag r-{role}'>{role}</span>"
 
def _conf_color(c: float) -> str:
    return "#2dce89" if c >= 0.65 else ("#ffc800" if c >= 0.55 else "#8b949e")
 
def _safe_tag(name: str) -> str:
    """Gera tag curta limpa para usar como parte de key de widget."""
    return re.sub(r"[^A-Za-z0-9]", "", name)[:6] or "T"
 
 
def _build_team_from_raw(raw: dict) -> TeamProfile:
    """Converte dict do scraper em TeamProfile com stats reais quando disponíveis."""
    team = TeamProfile(
        name       = raw.get("team_name") or extract_team_name(raw.get("url", "")),
        tag        = raw.get("tag", ""),
        region     = raw.get("region", ""),
        source_url = raw.get("url", ""),
        scraped_at = datetime.now().isoformat(),
    )
 
    for p in raw.get("players", []):
        team.players.append(PlayerStats(
            name                 = p["name"],
            role                 = p.get("role", "Flex"),
            top_agents           = p.get("top_agents", []),
            # Stats reais injetados pelo scraper via /team/stats — zeros se não disponível
            rating               = float(p.get("rating", 0.0)),
            acs                  = float(p.get("acs",    0.0)),
            kda                  = float(p.get("kda",    0.0)),
            first_kills_per_round  = float(p.get("first_kills_per_round",  0.0)),
            first_deaths_per_round = float(p.get("first_deaths_per_round", 0.0)),
            kills_per_round      = float(p.get("kills_per_round",  0.0)),
            deaths_per_round     = float(p.get("deaths_per_round", 0.0)),
            assists_per_round    = float(p.get("assists_per_round",0.0)),
        ))
 
    form               = get_recent_form_from_results(raw.get("recent_results", []))
    team.recent_form   = form
    team.recent_wins   = form.count("W")
    team.recent_losses = form.count("L")
 
    # ── Stats reais por mapa (W/L da aba /team/stats/) ──
    for ms_raw in raw.get("map_stats", []):
        team.map_stats.append(TeamMapStats(
            map_name     = ms_raw["map_name"],
            wins         = ms_raw.get("wins", 0),
            losses       = ms_raw.get("losses", 0),
            times_played = ms_raw.get("times_played", 0),
        ))
 
    return team
 
 
def load_team_from_url(url: str, force_refresh: bool = False) -> tuple[TeamProfile, bool]:
    raw        = scrape_url(url, force_refresh=force_refresh)
    from_cache = raw.get("_from_cache", False)
    return _build_team_from_raw(raw), from_cache
 
 
# ══════════════════════════════════════════════════════════════════════════════
# INPUT
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 🏆 Inserir Times")
 
col_a, col_b = st.columns(2)
with col_a:
    url_a = st.text_input("🔴 URL Time A",
                          placeholder="https://www.vlr.gg/team/2406/furia",
                          key="url_a")
with col_b:
    url_b = st.text_input("🔵 URL Time B",
                          placeholder="https://www.vlr.gg/team/4/fnatic",
                          key="url_b")
 
col_btn, col_chk = st.columns([3, 1])
with col_btn:
    run_btn = st.button("⚡ Analisar Partida", type="primary", use_container_width=True)
with col_chk:
    force = st.checkbox("🔄 Forçar atualização", value=False,
                        help="Ignora cache e refaz o scraping")
 
if run_btn:
    if not url_a or not url_b:
        st.error("Preencha as duas URLs.")
        st.stop()
    if url_a.strip() == url_b.strip():
        st.error("As duas URLs são iguais.")
        st.stop()
 
    team_a = team_b = None
    errors: list[str] = []
 
    with st.status("🔍 Carregando dados...", expanded=True) as status:
        for label, url, icon in [("Time A", url_a, "🔴"), ("Time B", url_b, "🔵")]:
            st.write(f"{icon} Buscando **{extract_team_name(url)}**...")
            try:
                t, from_cache = load_team_from_url(url.strip(), force_refresh=force)
                src    = "💾 cache" if from_cache else "🌐 scraping"
                real_p = sum(1 for p in t.players if p.has_real_stats)
                st.write(f"   ✅ {t.name} — {len(t.players)} players "
                         f"({real_p} com stats reais) via {src}")
                if label == "Time A": team_a = t
                else:                 team_b = t
            except Exception as e:
                errors.append(f"{label}: {e}")
                st.write(f"   ❌ Falha: {e}")
 
        if errors:
            status.update(label="❌ Erro", state="error")
            for err in errors: st.error(err)
            st.stop()
        else:
            status.update(label="✅ Pronto!", state="complete")
 
    st.session_state.update({
        "team_a":      team_a,
        "team_b":      team_b,
        "teams_ready": True,
        "series_fmt":  series_format,
    })
 
 
# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.get("teams_ready"):
    team_a: TeamProfile = st.session_state["team_a"]
    team_b: TeamProfile = st.session_state["team_b"]
    fmt                 = st.session_state.get("series_fmt", "BO3")
 
    # Garante pool atualizado antes de calcular
    _m.VALORANT_MAPS = active_pool
 
    pred  = full_series_prediction(team_a, team_b, series_format=fmt)
    veto  = pred["veto"]
    score = f"{pred['predicted_series_score_a']}–{pred['predicted_series_score_b']}"
    w_clr = "#ff4655" if pred["predicted_series_winner"] == team_a.name else "#00bfff"
 
    # Tags seguras para keys de widgets
    tag_a = _safe_tag(team_a.name)
    tag_b = _safe_tag(team_b.name)
    if not team_a.tag: team_a.tag = tag_a
    if not team_b.tag: team_b.tag = tag_b
 
    st.markdown("---")
 
    # ── Winner Banner ──
    st.markdown(f"""
    <div class="winner-box">
        <div style='color:#8b949e;font-size:0.78rem;letter-spacing:2px;text-transform:uppercase;'>
            Previsão · {fmt} · Pool: {len(active_pool)} mapas
        </div>
        <div style='font-size:2rem;font-weight:900;color:{w_clr};letter-spacing:2px;margin:6px 0;'>
            🏆 {pred["predicted_series_winner"].upper()}
        </div>
        <div style='color:#aaa;font-size:1.05rem;'>
            {team_a.name}
            <b style='color:#f0f0f0;'> {score} </b>
            {team_b.name}
        </div>
        <div style='margin-top:8px;font-size:0.82rem;'>
            <span style='color:#555;'>Confiança da série: </span>
            <span style='color:{_conf_color(pred["series_confidence"])};font-weight:600;'>
                {pred["series_confidence"]*100:.0f}%
            </span>
            &nbsp;&nbsp;·&nbsp;&nbsp;
            <span style='color:#555;font-size:0.78rem;'>
                (média das probs. por mapa — teto 85%)
            </span>
        </div>
        <div style='margin-top:6px;font-size:0.75rem;color:#444;'>
            {pred["data_quality_a"]} &nbsp;·&nbsp; {pred["data_quality_b"]}
        </div>
    </div>
    """, unsafe_allow_html=True)
 
    # Aviso se veto ficou incompleto
    max_maps = {"BO3": 3, "BO1": 1, "BO5": 5}.get(fmt, 3)
    if len(pred["map_results"]) < max_maps:
        st.warning(
            f"⚠️ Veto incompleto — apenas {len(pred['map_results'])} mapa(s) simulado(s) "
            f"de {max_maps} esperados. Adicione mais mapas no pool da sidebar."
        )
 
    tab1, tab2, tab3, tab4 = st.tabs([
        "👥 Times & Lineup", "🗺️ Mapas & Previsão",
        "🎯 Veto Simulado",  "📊 Análise Detalhada",
    ])
 
    # ═══════════════════════════════════════════════════════════
    # TAB 1 — TIMES & LINEUP
    # ═══════════════════════════════════════════════════════════
    with tab1:
        col_ta, col_tb = st.columns(2)
        for col, team, clr, side in [
            (col_ta, team_a, "#ff4655", "a"),
            (col_tb, team_b, "#00bfff", "b"),
        ]:
            with col:
                cs   = pred[f"combat_strength_{side}"]
                form = pred[f"form_{side}"]
 
                st.markdown(
                    f"<h3 style='color:{clr};margin-bottom:4px;'>{team.name}"
                    f"<span style='color:#444;font-size:0.8rem;margin-left:8px;'>"
                    f"[{team.tag}]</span></h3>",
                    unsafe_allow_html=True,
                )
                st.caption(f"{team.region}  ·  {team.data_quality}  ·  {team.source_url}")
 
                k1,k2,k3,k4 = st.columns(4)
                k1.markdown(_kpi("Combat Str.", f"{cs*100:.0f}"),          unsafe_allow_html=True)
                k2.markdown(_kpi("Avg Rating",  f"{team.avg_rating:.2f}"), unsafe_allow_html=True)
                k3.markdown(_kpi("Avg ACS",     f"{team.avg_acs:.0f}"),    unsafe_allow_html=True)
                k4.markdown(_kpi("Avg KDA",     f"{team.avg_kda:.2f}"),    unsafe_allow_html=True)
 
                k5,k6,k7,k8 = st.columns(4)
                # Win Rate = vitórias / total das partidas recentes scraped
                total_recent = team.recent_wins + team.recent_losses
                wr_str = f"{team.win_rate*100:.0f}%  ({team.recent_wins}W-{team.recent_losses}L)" if total_recent > 0 else "—"
                k5.markdown(_kpi("Win Rate",  wr_str),                             unsafe_allow_html=True)
                k6.markdown(_kpi("FK Adv.",   f"{team.fk_advantage:+.3f}"),        unsafe_allow_html=True)
                k7.markdown(_kpi("Forma (10)", f"{form*100:.0f}%" if team.recent_form else "—"), unsafe_allow_html=True)
                k8.markdown(_kpi("Partidas",  str(total_recent) if total_recent else "—"),        unsafe_allow_html=True)
 
                # Forma recente = sequência de W/L das últimas partidas (mais recente à direita)
                st.markdown("**Forma recente** <span style='color:#555;font-size:0.75rem;font-weight:400;'>(resultado de cada série — mais recente →)</span>", unsafe_allow_html=True)
                if team.recent_form:
                    form_html = " ".join([
                        f"<span style='background:{'#2dce89' if r=='W' else '#ff4655'};"
                        f"color:#fff;padding:2px 8px;border-radius:4px;"
                        f"font-weight:700;font-size:0.82rem;'>{r}</span>"
                        for r in team.recent_form[-10:]
                    ])
                else:
                    form_html = "<span style='color:#555;font-size:0.85rem;'>— sem histórico de partidas disponível</span>"
                st.markdown(form_html, unsafe_allow_html=True)
 
                st.markdown("**Lineup atual**")
                if not team.players:
                    st.caption("Nenhum jogador encontrado.")
                for p in team.players:
                    agents_str = " · ".join(p.top_agents[:3]) if p.top_agents else "—"
                    if p.has_real_stats:
                        stats_str = (
                            f"<b style='color:{clr};'>{p.effective_rating:.2f}</b>"
                            f" rtg · {p.effective_acs:.0f} ACS · {p.effective_kda:.2f} KDA"
                        )
                    else:
                        stats_str = (
                            f"<span style='color:#555;font-size:0.75rem;'>"
                            f"default {p.effective_rating:.1f} rtg</span>"
                        )
                    st.markdown(f"""
                    <div style='display:flex;justify-content:space-between;align-items:center;
                                padding:5px 0;border-bottom:1px solid #21262d;'>
                        <div>
                            <span style='color:#f0f0f0;font-weight:600;'>{p.name}</span>
                            {_role_tag(p.role)}
                            <span style='color:#555;font-size:0.72rem;margin-left:6px;'>
                                ({agents_str})
                            </span>
                        </div>
                        <div style='font-size:0.8rem;color:#8b949e;'>{stats_str}</div>
                    </div>
                    """, unsafe_allow_html=True)
 
    # ═══════════════════════════════════════════════════════════
    # TAB 2 — MAPAS & PREVISÃO
    # ═══════════════════════════════════════════════════════════
    with tab2:
        pool_display = veto["map_pool_used"]
        st.markdown(f"### Previsão por Mapa — {fmt}")
        st.caption(f"Pool ativo ({len(pool_display)}): {' · '.join(pool_display)}")
 
        if not pred["map_results"]:
            st.warning("Nenhum mapa para prever. Verifique o pool na sidebar.")
        else:
            for res in pred["map_results"]:
                p_a    = res["prob_a"]
                p_b    = res["prob_b"]
                w      = res["predicted_winner"]
                conf   = res["confidence"]
                ccls   = "map-a" if w == team_a.name else ("map-b" if w == team_b.name else "map-eq")
                w_clr2 = "#ff4655" if w == team_a.name else "#00bfff"
                map_loc   = ALL_MAPS.get(res["map"], "")
                loc_str   = (f"<span style='color:#555;font-size:0.75rem;'>"
                             f" · {map_loc}</span>") if map_loc else ""
                needed_tag = (
                    "<span style='color:#555;font-size:0.72rem;"
                    "border:1px solid #333;border-radius:3px;"
                    "padding:1px 5px;margin-left:6px;'>if needed</span>"
                    if res.get("if_needed") else ""
                )
 
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(f"""
                    <div class="map-card {ccls}">
                        <div style='display:flex;justify-content:space-between;align-items:center;'>
                            <span style='font-size:1.05rem;font-weight:700;color:#f0f0f0;'>
                                🗺️ {res["map"]}{loc_str}{needed_tag}
                            </span>
                            <span style='color:{w_clr2};font-weight:700;'>🏆 {w}</span>
                        </div>
                        <div style='margin-top:5px;font-size:0.82rem;color:#8b949e;
                                    display:flex;justify-content:space-between;align-items:center;'>
                            <span>{team_a.name}: <b style='color:#ff4655;'>{p_a*100:.1f}%</b></span>
                            <span style='font-size:0.75rem;color:{_conf_color(conf)};'>
                                Conf. mapa: {conf*100:.0f}%
                            </span>
                            <span>{team_b.name}: <b style='color:#00bfff;'>{p_b*100:.1f}%</b></span>
                        </div>
                    {"<div style='margin-top:3px;font-size:0.72rem;color:#555;'>⚠️ estimativa — sem histórico real deste mapa</div>" if not res.get("has_map_data_a") and not res.get("has_map_data_b") else ""}
                    </div>
                    """, unsafe_allow_html=True)
                with c2:
                    chart_key = f"chart_{res['map']}_{tag_a}_{tag_b}"
                    fig = go.Figure(go.Bar(
                        x=[p_a*100, p_b*100],
                        y=[team_a.name, team_b.name],
                        orientation="h",
                        marker_color=["#ff4655","#00bfff"],
                        text=[f"{p_a*100:.0f}%", f"{p_b*100:.0f}%"],
                        textposition="outside",
                    ))
                    fig.update_layout(
                        height=80, margin=dict(l=0,r=5,t=0,b=0),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        xaxis=dict(range=[0,100], showticklabels=False, showgrid=False),
                        yaxis=dict(showgrid=False, tickfont=dict(color="#8b949e",size=10)),
                        showlegend=False, font=dict(color="#f0f0f0",size=10),
                    )
                    st.plotly_chart(fig, use_container_width=True,
                                   config={"displayModeBar": False},
                                   key=chart_key)
 
            # Radar — sempre exibido, com aviso quando sem dados reais
            st.markdown("---")
            st.markdown("### 📈 Win Rate por Mapa")
            if not pred.get("has_real_map_data"):
                st.caption(
                    "⚠️ Nenhum time possui histórico real de resultados por mapa. "
                    "Os valores abaixo são 50% (neutro) — o gráfico é ilustrativo."
                )
            wr_a = [team_a.get_map_stat(m).win_rate * 100 for m in pool_display]
            wr_b = [team_b.get_map_stat(m).win_rate * 100 for m in pool_display]
            if len(pool_display) >= 3:
                fig_r = go.Figure()
                fig_r.add_trace(go.Scatterpolar(
                    r=wr_a+[wr_a[0]], theta=pool_display+[pool_display[0]],
                    fill="toself", name=team_a.name,
                    line=dict(color="#ff4655",width=2), fillcolor="rgba(255,70,85,0.12)"))
                fig_r.add_trace(go.Scatterpolar(
                    r=wr_b+[wr_b[0]], theta=pool_display+[pool_display[0]],
                    fill="toself", name=team_b.name,
                    line=dict(color="#00bfff",width=2), fillcolor="rgba(0,191,255,0.12)"))
                fig_r.update_layout(
                    polar=dict(bgcolor="#161b22",
                        radialaxis=dict(visible=True,range=[0,100],
                            gridcolor="#21262d",tickfont=dict(color="#555")),
                        angularaxis=dict(gridcolor="#21262d",tickfont=dict(color="#aaa"))),
                    paper_bgcolor="#0d1117", height=420,
                    margin=dict(l=30,r=30,t=30,b=30),
                    legend=dict(font=dict(color="#f0f0f0")),
                    font=dict(color="#f0f0f0"),
                )
                st.plotly_chart(fig_r, use_container_width=True,
                               config={"displayModeBar": False},
                               key=f"radar_{tag_a}_{tag_b}")
 
    # ═══════════════════════════════════════════════════════════
    # TAB 3 — VETO SIMULADO
    # ═══════════════════════════════════════════════════════════
    with tab3:
        st.markdown("### 🎯 Simulação de Veto")
        st.caption(
            "Pool = mapas selecionados na sidebar. "
            "Bans = evitar força adversária. Picks = maximizar WR própria."
        )
 
        if not veto["veto_sequence"]:
            st.warning("Veto vazio — pool insuficiente. Adicione mapas na sidebar.")
        else:
            col_v, col_s = st.columns([2, 1])
            with col_v:
                for step in veto["veto_sequence"]:
                    act  = step["action"]
                    bcls = {"BAN":"b-ban","PICK":"b-pick","DECIDER":"b-decider"}.get(act,"b-pick")
                    aclr = {"BAN":"#ff4655","PICK":"#00bfff","DECIDER":"#ffc800"}.get(act,"#fff")
                    icon = {"BAN":"🚫","PICK":"✅","DECIDER":"⚔️"}.get(act,"")
                    map_loc = ALL_MAPS.get(step["map"], "")
                    loc_txt = (f" <span style='color:#444;font-size:0.72rem;'>"
                               f"({map_loc})</span>") if map_loc else ""
                    st.markdown(f"""
                    <div style='display:flex;align-items:center;padding:0.6rem 0;
                                border-bottom:1px solid #21262d;'>
                        <span style='width:24px;color:#444;font-size:0.8rem;'>{step["step"]}.</span>
                        <span class="veto-badge {bcls}">{icon} {act}</span>
                        <span style='color:#8b949e;font-size:0.83rem;width:150px;'>{step["team"]}</span>
                        <span style='color:{aclr};font-weight:700;margin:0 8px;'>
                            {step["map"]}{loc_txt}
                        </span>
                        <span style='color:#555;font-size:0.75rem;'>{step["reason"]}</span>
                    </div>
                    """, unsafe_allow_html=True)
 
            with col_s:
                def _mini(title: str, items: list, clr: str) -> str:
                    li = "".join(f"<li style='color:{clr};padding:1px 0;'>{i}</li>"
                                 for i in items)
                    return (f"<p style='color:#8b949e;margin:4px 0;font-size:0.82rem;'>"
                            f"<b>{title}</b></p>"
                            f"<ul style='margin:0;padding-left:1rem;'>{li}</ul>")
 
                st.markdown("**Resumo**")
                st.markdown(_mini(f"🚫 {team_a.name} bans", veto["bans_a"],  "#ff4655"), unsafe_allow_html=True)
                st.markdown(_mini(f"🚫 {team_b.name} bans", veto["bans_b"],  "#ff4655"), unsafe_allow_html=True)
                st.markdown(_mini(f"✅ {team_a.name} pick",  veto["picks_a"], "#00bfff"), unsafe_allow_html=True)
                st.markdown(_mini(f"✅ {team_b.name} pick",  veto["picks_b"], "#00bfff"), unsafe_allow_html=True)
                if veto["deciders"]:
                    st.markdown(_mini("⚔️ Decider", veto["deciders"], "#ffc800"), unsafe_allow_html=True)
 
                st.markdown("---")
                st.markdown("**Mapas previstos**")
                if not veto["played_maps"]:
                    st.caption("Nenhum mapa — pool insuficiente.")
                for m in veto["played_maps"]:
                    r = next((x for x in pred["map_results"] if x["map"] == m), None)
                    if r:
                        wc = "#ff4655" if r["predicted_winner"] == team_a.name else "#00bfff"
                        st.markdown(f"""
                        <div style='display:flex;justify-content:space-between;padding:3px 0;'>
                            <span style='color:#f0f0f0;'>🗺️ {m}</span>
                            <span style='color:{wc};font-weight:600;font-size:0.82rem;'>
                                {r["predicted_winner"]} ({r["confidence"]*100:.0f}%)
                            </span>
                        </div>""", unsafe_allow_html=True)
 
    # ═══════════════════════════════════════════════════════════
    # TAB 4 — ANÁLISE DETALHADA
    # ═══════════════════════════════════════════════════════════
    with tab4:
 
        # helpers locais
        def _eff_rating(p: PlayerStats) -> float:
            return p.rating if p.rating > 0 else 1.0
 
        def _eff_acs(p: PlayerStats) -> float:
            return p.acs if p.acs > 0 else 210.0
 
        def _eff_kda(p: PlayerStats) -> float:
            return p.kda if p.kda > 0 else 1.0
 
        def _fk_adv_p(p: PlayerStats) -> float:
            return round(p.first_kills_per_round - p.first_deaths_per_round, 4)
 
        # ── Monta DataFrame de jogadores ─────────────────────────────────────
        player_rows = []
        for team, clr in [(team_a, "🔴"), (team_b, "🔵")]:
            for p in team.players:
                player_rows.append({
                    "Time":    f"{clr} {team.name}",
                    "Jogador": p.name,
                    "Role":    p.role,
                    "Rating":  round(_eff_rating(p), 3),
                    "ACS":     round(_eff_acs(p),    1),
                    "KDA":     round(_eff_kda(p),    3),
                    "FK Adv.": round(_fk_adv_p(p),   4),
                    "Agentes": " / ".join(p.top_agents[:3]) if p.top_agents else "—",
                    "Dados":   "✅ real" if p.has_real_stats else "⚠️ default",
                })
 
        df_players = pd.DataFrame(player_rows)
 
        # ── 1. Filtro de ranking ──────────────────────────────────────────────
        st.markdown("#### 🏅 Jogadores")
        view_mode = st.radio(
            "Visualização",
            ["🏆 Ranking Geral (por Rating)", "👥 Agrupado por Time"],
            horizontal=True,
            key="tab4_view",
        )
 
        if "Ranking" in view_mode:
            df_show = (
                df_players
                .sort_values("Rating", ascending=False)
                .reset_index(drop=True)
            )
            df_show.index += 1
            df_show.index.name = "Rank"
            st.caption("Todos os jogadores ordenados por Rating (maior → menor). ⚠️ default = stat não disponível — usa 1.0.")
        else:
            df_show = (
                df_players
                .sort_values(["Time", "Rating"], ascending=[True, False])
                .reset_index(drop=True)
            )
            st.caption("Agrupado por time, ordenado por Rating dentro de cada grupo.")
 
        styled_p = (
            df_show.style
            .background_gradient(subset=["Rating"], cmap="RdYlGn", vmin=0.7,  vmax=1.4)
            .background_gradient(subset=["ACS"],    cmap="RdYlGn", vmin=150,  vmax=290)
            .background_gradient(subset=["KDA"],    cmap="RdYlGn", vmin=0.7,  vmax=2.2)
            .format({
                "Rating":  "{:.3f}",
                "ACS":     "{:.0f}",
                "KDA":     "{:.3f}",
                "FK Adv.": "{:+.4f}",
            })
        )
        st.dataframe(styled_p, use_container_width=True, height=390)
 
        # ── 2. Exportar CSV ───────────────────────────────────────────────────
        # utf-8-sig garante compatibilidade com Excel (caracteres especiais)
        csv_bytes = df_show.to_csv(index=True, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            label="⬇️ Exportar tabela para CSV",
            data=csv_bytes,
            file_name=f"vsa_{tag_a}_vs_{tag_b}_players.csv",
            mime="text/csv",
            key="tab4_csv",
        )
 
        st.markdown("---")
 
        # ── 3. Comparativo de times ───────────────────────────────────────────
        st.markdown("#### 🆚 Comparativo de Times")
 
        def _wl_str(team: TeamProfile) -> str:
            t = team.recent_wins + team.recent_losses
            return f"{team.recent_wins}W-{team.recent_losses}L" if t else "—"
 
        df_comp = pd.DataFrame([
            {
                "Time":               team_a.name,
                "Combat Str. (%)":    round(pred["combat_strength_a"] * 100, 1),
                "Avg Rating":         round(team_a.avg_rating, 3),
                "Avg ACS":            round(team_a.avg_acs, 1),
                "Avg KDA":            round(team_a.avg_kda, 3),
                "FK Adv. (time)":     round(team_a.fk_advantage, 4),
                "Win Rate (%)":       round(team_a.win_rate * 100, 1),
                "Partidas":           _wl_str(team_a),
                "Forma":              "".join(team_a.recent_form[-10:]) or "—",
            },
            {
                "Time":               team_b.name,
                "Combat Str. (%)":    round(pred["combat_strength_b"] * 100, 1),
                "Avg Rating":         round(team_b.avg_rating, 3),
                "Avg ACS":            round(team_b.avg_acs, 1),
                "Avg KDA":            round(team_b.avg_kda, 3),
                "FK Adv. (time)":     round(team_b.fk_advantage, 4),
                "Win Rate (%)":       round(team_b.win_rate * 100, 1),
                "Partidas":           _wl_str(team_b),
                "Forma":              "".join(team_b.recent_form[-10:]) or "—",
            },
        ]).set_index("Time")
 
        num_cols_comp = ["Combat Str. (%)", "Avg Rating", "Avg ACS", "Avg KDA", "Win Rate (%)"]
        styled_comp = (
            df_comp.style
            .background_gradient(subset=num_cols_comp, cmap="RdYlGn", axis=0)
            .format({
                "Combat Str. (%)": "{:.1f}",
                "Avg Rating":      "{:.3f}",
                "Avg ACS":         "{:.0f}",
                "Avg KDA":         "{:.3f}",
                "FK Adv. (time)":  "{:+.4f}",
                "Win Rate (%)":    "{:.1f}",
            })
        )
        st.dataframe(styled_comp, use_container_width=True)
 
        st.markdown("---")
 
        # ── 4. Performance por mapa (pool ativo) ─────────────────────────────
        st.markdown("#### 🗺️ Performance por Mapa")
        st.caption(
            "Dados reais via vlr.gg/team/stats. "
            "Células '—' = mapa sem histórico para este time."
        )
 
        pool_maps = veto["map_pool_used"]
        map_rows  = []
        for mp in pool_maps:
            ms_a = team_a.get_map_stat(mp)
            ms_b = team_b.get_map_stat(mp)
            has_a = ms_a.wins + ms_a.losses > 0
            has_b = ms_b.wins + ms_b.losses > 0
            map_pred = next((r for r in pred["map_results"] if r["map"] == mp), None)
 
            map_rows.append({
                "Mapa":                   mp,
                f"{team_a.name} WR (%)":  round(ms_a.win_rate * 100, 1) if has_a else None,
                f"{team_a.name} (W-L)":   f"{ms_a.wins}-{ms_a.losses}"  if has_a else "—",
                f"{team_b.name} WR (%)":  round(ms_b.win_rate * 100, 1) if has_b else None,
                f"{team_b.name} (W-L)":   f"{ms_b.wins}-{ms_b.losses}"  if has_b else "—",
                "Favorito":               map_pred["predicted_winner"]   if map_pred else "—",
                "Conf. (%)":              round(map_pred["confidence"] * 100, 1) if map_pred else None,
                "If needed":              "⚠️" if (map_pred and map_pred.get("if_needed")) else "",
            })
 
        df_maps = pd.DataFrame(map_rows).set_index("Mapa")
        wr_cols = [c for c in df_maps.columns if "WR (%)" in c or c == "Conf. (%)"]
        styled_maps = (
            df_maps.style
            .background_gradient(subset=wr_cols, cmap="RdYlGn", vmin=20, vmax=80)
            .format({c: "{:.1f}" for c in wr_cols}, na_rep="—")
        )
        st.dataframe(styled_maps, use_container_width=True)
 
    st.markdown("---")
    st.markdown("""
    <div style='text-align:center;color:#444;font-size:0.75rem;padding:0.8rem;'>
        VALORANT SCOUT AGENT &nbsp;·&nbsp; VLR.gg &amp; Liquipedia
        &nbsp;·&nbsp; Stats via /team/stats &nbsp;·&nbsp; Cache 24h &nbsp;·&nbsp;
        <b style='color:#ff4655;'>Uso educacional — não é recomendação de apostas</b>
    </div>
    """, unsafe_allow_html=True)
 
else:
    st.markdown("""
    <div style='text-align:center;padding:4rem 2rem;color:#555;'>
        <div style='font-size:4rem;margin-bottom:1rem;'>🎯</div>
        <div style='font-size:1.15rem;color:#8b949e;margin-bottom:1.5rem;'>
            Cole as URLs dos times e clique em
            <b style='color:#ff4655;'>Analisar Partida</b>.
        </div>
        <div style='font-size:0.85rem;line-height:2.2;'>
            ✅ Stats reais via <code>vlr.gg/team/stats/ID/nome</code><br>
            ✅ Role detectada pelos 3 agentes mais jogados<br>
            ✅ Coach / Staff / Manager filtrados do roster<br>
            ✅ Cache local 24h — scraping só quando necessário<br>
            ✅ Pool híbrido — sugestão VLR + controle manual (12 mapas)<br>
            ✅ Aviso quando pool insuficiente para o formato da série<br>
            ✅ Veto blindado — sem crash com pool pequeno<br>
            ✅ Fallback de stats (Rating 1.0 / KDA 1.0 / ACS 210)
        </div>
    </div>
    """, unsafe_allow_html=True)
 