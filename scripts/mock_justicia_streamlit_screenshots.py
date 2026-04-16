"""
Écran unique pour capture rapide (UI seule, sans backend RAG).

Pour un **compte rendu de milestone** multi-écrans (JusticIA), préférer :
  scripts/justicia_slide_deck.py
et le Markdown : presentations/justicia-metaketing-aziz/deck.md

Usage :
  pip install streamlit
  streamlit run scripts/mock_justicia_streamlit_screenshots.py --server.port 8510 --server.address 0.0.0.0
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st


def _repo_root() -> Path:
    """Racine du dépôt : fonctionne si le script est dans `scripts/` ou à la racine."""
    here = Path(__file__).resolve().parent
    if (here / "image").is_dir():
        return here
    if (here.parent / "image").is_dir():
        return here.parent
    return here


REPO_ROOT = _repo_root()
IMG = REPO_ROOT / "image" / "justicia.png"
AITUBO = REPO_ROOT / "image" / "aitubo.jpg"


def _bg_css() -> str:
    return """
    <style>
    .block-container { padding-top: 1rem; max-width: 1200px; }
    div[data-testid="stSidebar"] { background: linear-gradient(180deg, #1a1d29 0%, #252836 100%); }
    div[data-testid="stSidebar"] * { color: #e8eaed !important; }
    </style>
    """


def main() -> None:
    st.set_page_config(
        page_title="JusticIA — Assistant",
        page_icon="⚖️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_bg_css(), unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("### Paramètres")
        st.selectbox("Modèle", ["Llama 3.1 — Instruct (CPU)"], disabled=True)
        st.selectbox("Base documentaire", ["faiss_JusticIA — index courant"], disabled=True)
        st.selectbox("Pipeline", ["Retrieval hybride (dense + BM25)"], disabled=True)
        st.slider("Température", 0.0, 1.0, 0.1, disabled=True)
        st.markdown("---")
        st.download_button(
            label="Exporter la conversation (JSON)",
            data='{"session":"active","exported_at":"2026-04-15T10:00:00Z","messages":[]}',
            file_name="conversation.json",
            mime="application/json",
        )

    header_cols = st.columns([1, 6])
    with header_cols[0]:
        if IMG.is_file():
            st.image(str(IMG), width=64)
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

    user_av = str(AITUBO) if AITUBO.is_file() else "🧑‍💼"
    ai_av = str(IMG) if IMG.is_file() else "⚖️"
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


if __name__ == "__main__":
    main()
