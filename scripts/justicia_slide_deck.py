"""
Vues plein écran pour captures du compte rendu de milestone JusticIA — UI seule, sans backend RAG.
Dépendance : streamlit.

  streamlit run scripts/justicia_slide_deck.py --server.port 8510 --server.address 0.0.0.0

Navigation :
  • Barre latérale : liens vers chaque écran.
  • URL : ?slide=1 … ?slide=6 — ajoutez &clean=1 pour masquer la barre latérale (capture propre).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import streamlit as st

_here = Path(__file__).resolve().parent
if (_here / "image").is_dir():
    REPO_ROOT = _here
elif (_here.parent / "image").is_dir():
    REPO_ROOT = _here.parent
else:
    REPO_ROOT = _here.parent

IMG = REPO_ROOT / "image" / "justicia.png"
AITUBO = REPO_ROOT / "image" / "aitubo.jpg"


def _justicia_theme_css(*, hide_sidebar: bool) -> str:
    """Thème aligné sur l’UI historique JusticIA (ragger_css : fond dégradé, mode sombre)."""
    grad = (
        "linear-gradient(to right, rgba(122, 119, 185, 0.42), rgba(159, 107, 172, 0.42), "
        "rgba(194, 94, 154, 0.42), rgba(219, 86, 134, 0.42), rgba(232, 82, 111, 0.42), "
        "rgba(240, 87, 87, 0.42), rgba(243, 99, 64, 0.42), rgba(237, 120, 48, 0.42))"
    )
    base = f"""
    <style>
    .stApp {{
        background-color: #0b0d12 !important;
    }}
    [data-testid="stAppViewContainer"] > .main {{
        background-image: {grad};
        background-size: cover;
        background-position: center center;
        background-repeat: no-repeat;
        background-attachment: fixed;
    }}
    [data-testid="stHeader"] {{
        background: rgba(0,0,0,0) !important;
    }}
    [data-testid="stSidebarContent"],
    [data-testid="stSidebarUserContent"] {{
        background-image: {grad} !important;
        background-size: cover !important;
        background-attachment: fixed !important;
    }}
    section[data-testid="stSidebar"] {{
        background: linear-gradient(180deg, #12151c 0%, #1a1f2e 100%) !important;
    }}
    section[data-testid="stSidebar"] * {{
        color: #e8eaed !important;
    }}
    .block-container {{
        padding-top: 1rem;
        max-width: 1200px;
    }}
    .main .block-container, .stMarkdown, .stMarkdown p, .stMarkdown li,
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {{
        color: #e6edf3 !important;
    }}
    [data-testid="stCaption"] {{
        color: #8b949e !important;
    }}
    div[data-testid="stMetric"] label {{
        color: #8b949e !important;
    }}
    [data-testid="stMetricValue"] {{
        color: #58a6ff !important;
    }}
    .stAlert {{
        background-color: rgba(13, 45, 85, 0.92) !important;
        border-left-color: #388bfd !important;
        color: #e6edf3 !important;
    }}
    [data-testid="stExpander"] {{
        background-color: rgba(22, 27, 38, 0.85) !important;
        border: 1px solid #30363d !important;
        border-radius: 8px !important;
    }}
    footer {{ visibility: hidden; height: 0; }}
    [data-testid="stChatMessage"] {{
        background-color: rgba(22, 27, 34, 0.92) !important;
        border: 1px solid #30363d !important;
    }}
    [data-testid="stChatInput"] {{
        background-color: #0d1117 !important;
    }}
    """
    if hide_sidebar:
        base += """
    section[data-testid="stSidebar"] { display: none !important; }
    div[data-testid="collapsedControl"] { display: none !important; }
    """
    base += "</style>"
    return base


def _qp_get(name: str, default: str) -> str:
    try:
        q = st.query_params
        v = q.get(name, default)
        if isinstance(v, (list, tuple)):
            return str(v[0]) if v else default
        return str(v) if v is not None else default
    except Exception:
        return default


def _qp_clean() -> bool:
    return _qp_get("clean", "0").lower() in ("1", "true", "yes")


def _user_ai_avatars() -> tuple[str, str]:
    u = str(AITUBO) if AITUBO.is_file() else "🧑‍💼"
    a = str(IMG) if IMG.is_file() else "⚖️"
    return u, a


def render_slide_1_cover() -> None:
    c1, c2 = st.columns([1, 4])
    with c1:
        if IMG.is_file():
            st.image(str(IMG), width=96)
        else:
            st.markdown("# ⚖️")
    with c2:
        st.markdown("# JusticIA")
        st.markdown(
            "### Recherche augmentée sur votre corpus juridique — réponses sourcées, "
            "contrôlables par les équipes métiers."
        )
    st.markdown("---")
    a, b, c = st.columns(3)
    with a:
        st.markdown("#### Ingestion")
        st.caption(
            "PDF, Office, e-mail — texte natif et **OCR** pour les pièces numérisées."
        )
    with b:
        st.markdown("#### Retrieval hybride")
        st.caption("Index **dense** + **BM25** pour précision et rappel sur les actes.")
    with c:
        st.markdown("#### Prêt production")
        st.caption(
            "Socle **identité**, cloisonnement des bases et **traçabilité** des consultations."
        )


def _panel_parametres() -> None:
    st.markdown("##### Paramètres")
    st.selectbox("Modèle", ["Llama 3.1 — Instruct (CPU)"], disabled=True)
    st.selectbox("Base documentaire", ["faiss_JusticIA — index courant"], disabled=True)
    st.selectbox("Pipeline", ["Retrieval hybride (dense + BM25)"], disabled=True)
    st.slider("Température", 0.0, 1.0, 0.1, disabled=True)
    st.download_button(
        label="Exporter la conversation (JSON)",
        data='{"session":"active","exported_at":"2026-04-15T10:00:00Z","messages":[]}',
        file_name="conversation.json",
        mime="application/json",
    )


def render_slide_2_assistant() -> None:
    """Zone principale façon app : colonne gauche = paramètres (visible aussi en mode clean)."""
    st.markdown(
        """
        <style>
        div[data-testid="column"]:nth-of-type(1) div[data-testid="stVerticalBlock"] {
            background: rgba(18, 21, 28, 0.95) !important;
            border: 1px solid #30363d !important;
            border-radius: 12px !important;
            padding: 0.75rem 0.5rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    main = st.columns([1, 2.2])
    with main[0]:
        _panel_parametres()
    with main[1]:
        header_cols = st.columns([1, 6])
        with header_cols[0]:
            if IMG.is_file():
                st.image(str(IMG), width=56)
            else:
                st.markdown("### ⚖️")
        with header_cols[1]:
            st.markdown("## JusticIA")
            st.caption("Assistant juridique — recherche augmentée sur corpus indexé")

        c1, c2 = st.columns([2, 1])
        with c1:
            st.info(
                "**Sources** — Code de l’urbanisme, art. L.600-1 et s. ; CE, 3e et 4e ch., "
                "recours contentieux des décisions de non-conformité et de permis de construire."
            )
        with c2:
            st.metric("Dernière réponse", "1,2 s")

        st.markdown("---")
        user_av, ai_av = _user_ai_avatars()
        for role, text, av in [
            (
                "user",
                "Quels sont les délais de recours pour un refus de permis de construire ?",
                user_av,
            ),
            (
                "assistant",
                "Les recours contre un permis de construire refusé ou contre une décision de non-conformité "
                "relèvent en général du **recours contentieux** devant le tribunal administratif, dans un "
                "délai de **deux mois** à compter de la date de **notification** de la décision (ou, à défaut, "
                "de la date à laquelle la décision est **exécutoire** selon les cas).\n\n"
                "Les délais peuvent varier selon la nature exacte de l’acte attaqué et la procédure applicable ; "
                "il convient de contrôler les mentions de notification figurant sur le courrier et les textes "
                "en vigueur pour le dossier concerné.",
                ai_av,
            ),
        ]:
            with st.chat_message(role, avatar=av):
                st.markdown(text)

        st.chat_input("Posez votre question juridique…")


def render_slide_3_pipeline() -> None:
    st.markdown("## Chaîne de traitement")
    st.caption("De la pièce au modèle — même architecture que le POC livré sur corpus client.")
    st.markdown("---")
    cols = st.columns(5)
    labels = [
        ("Prétraitement", "Nettoyage, découpe sémantique"),
        ("Embeddings", "Modèle d’instructions adapté au domaine"),
        ("Index", "FAISS + persistance"),
        ("Retrieval", "Hybrid dense + BM25, rerank"),
        ("Génération", "LLM contrôlé, citations"),
    ]
    for col, (title, sub) in zip(cols, labels, strict=True):
        with col:
            st.markdown(f"**{title}**")
            st.caption(sub)
    st.markdown("---")
    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("Documents indexés (exemple)", "10")
    with m2:
        st.metric("Latence retrieval", "< 200 ms")
    with m3:
        st.metric("Disponibilité cible", "99,5 %")


def render_slide_4_sources() -> None:
    st.markdown("## Lecture des sources")
    st.caption("Chaque réponse renvoie aux passages du corpus — traçabilité pour le métier et le conformité.")
    st.markdown("---")
    with st.expander("Passage 1 — Code de l’urbanisme", expanded=True):
        st.markdown(
            "*« L.600-1 — Les décisions … peuvent être déférées au tribunal administratif … »* "
            "(extrait indicatif — fond documentaire client)."
        )
    with st.expander("Passage 2 — Jurisprudence administrative"):
        st.markdown(
            "*« Le délai du recours contentieux court à compter de la notification … »* "
            "(extrait indicatif)."
        )
    st.info(
        "**Pourquoi c’est important** — réduction du risque d’hallucination, "
        "audit des réponses, alignement avec vos bases internes."
    )


def render_slide_5_governance() -> None:
    st.markdown("## Accès, données, rôles")
    st.caption("Cadre entreprise : les utilisateurs métier travaillent dans un périmètre documentaire défini.")
    st.markdown("---")
    st.table(
        [
            {"Rôle": "Juriste / métier", "Accès": "Assistant + corpus du dossier", "Config. technique": "Non"},
            {"Rôle": "Admin données", "Accès": "Indexation, mises à jour", "Config. technique": "Oui"},
            {"Rôle": "DSI / sécurité", "Accès": "Journaux, politique de rétention", "Config. technique": "Oui"},
        ]
    )
    st.markdown(
        "**Isolation** — bases vectorielles et historiques de conversation **scindés par workspace** "
        "(équipe, mandat ou client selon votre modèle)."
    )


def render_slide_6_partenariat() -> None:
    st.markdown("## JusticIA × papAI — cadre contractuel (CP)")
    st.markdown(
        "**Licence papAI** — **3 utilisateurs** : **21 000 € HT / an** (TTC hors TVA export selon CP)."
    )
    st.markdown(
        "**Développements complémentaires** — **59 000 € HT** (forfait, Phases 1 et 2) :"
    )
    st.markdown(
        "- **Phase 1** — Intégration **CPU** de RAGGER + RAFT dans papAI ; premières briques RAG.\n"
        "- **Phase 2** — **Activation GPU** ; intégration **LAFT** dans papAI ; recherche juridique automatisée (périmètre CP)."
    )
    st.markdown("---")
    st.markdown(
        "**Infrastructure** — Déploiement **conteneurisé** (Kubernetes ou équivalent), certificats SSL, ports ; "
        "serveur **Unix**, **vCores**, **RAM** et **stockage** selon prérequis CP ; **Git**, **Docker**. "
        "Dimensionnement des workers par configuration papAI."
    )
    st.markdown(
        "**Ressources GPU** — Phase 2 : support **GPU** pour **inférence locale** et brique **LAFT** (modèles retenus, CP)."
    )
    st.caption(
        "Jalons détaillés et répartition en jours-homme : *Proposition d’accompagnement*."
    )


SLIDES: dict[str, tuple[str, Callable[[], None]]] = {
    "1": ("Couverture — proposition de valeur", render_slide_1_cover),
    "2": ("Assistant — conversation sourcée", render_slide_2_assistant),
    "3": ("Technique — pipeline d’indexation & retrieval", render_slide_3_pipeline),
    "4": ("Confiance — sources & traçabilité", render_slide_4_sources),
    "5": ("Entreprise — accès & gouvernance", render_slide_5_governance),
    "6": ("Cadre contractuel — phases, enveloppes, infra & GPU", render_slide_6_partenariat),
}


def main() -> None:
    slide = _qp_get("slide", "1")
    if slide not in SLIDES:
        slide = "1"
    clean = _qp_clean()

    st.set_page_config(
        page_title="JusticIA — Milestone",
        page_icon="⚖️",
        layout="wide",
        initial_sidebar_state="collapsed" if clean else "expanded",
    )
    st.markdown(_justicia_theme_css(hide_sidebar=clean), unsafe_allow_html=True)

    if not clean:
        with st.sidebar:
            st.markdown("### Écrans — milestone JusticIA")
            st.caption("Liens « propres » (sans ce menu) pour capture : ajoutez `&clean=1` à l’URL.")
            for key, (title, _) in SLIDES.items():
                st.markdown(f"**{key}.** {title}")
                st.markdown(
                    f"[Ouvrir écran {key} (clean)](?slide={key}&clean=1)",
                    help="Capture plein écran recommandée",
                )
            st.markdown("---")
            st.markdown(
                "**Astuce** : exportez les PNG dans `presentations/justicia-metaketing-aziz/screenshots/` "
                "avec les noms indiqués dans le compte rendu Markdown."
            )

    _, render = SLIDES[slide]
    if not clean:
        st.caption(f"Vue {slide}/6 — {SLIDES[slide][0]}")
    render()


if __name__ == "__main__":
    main()
