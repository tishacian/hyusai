import streamlit as st

from configuration import get_standalone_interface_config
from src.db.system_prompts import SystemPrompts
from src.standalone_interface.assets import omnirag_header
from src.standalone_interface.style import apply_omnirag_style
from src.utils import humanize_datetime


def init_prompt_session_state():
    if st.session_state.get("updated_by") is None:
        st.session_state.updated_by = ""
    if st.session_state.get("just_saved") is None:
        st.session_state.just_saved = False
    if st.session_state.get("just_reset") is None:
        st.session_state.just_reset = False
    if st.session_state.get("just_reset_all") is None:
        st.session_state.just_reset_all = False


def reset_all_section(updated_by: str):
    st.subheader("⚠️ Reset All Prompts")
    confirm_reset_all = st.checkbox("I confirm I want to reset all prompts to default")
    reset_all_button = st.button("Reset All", disabled=not confirm_reset_all)
    if reset_all_button and confirm_reset_all:
        if not updated_by.strip():
            st.error("'Updated by' field is required.")
        else:
            SystemPrompts.reset_all(updated_by=updated_by)
            st.session_state["just_reset_all"] = True
            st.rerun()
    if st.session_state.get("just_reset_all"):
        st.success("All prompts have been reset to defaults.")
        del st.session_state["just_reset_all"]


def update_section() -> str:
    language = st.selectbox("Select a language", options=SystemPrompts.get_languages())
    system_prompt = SystemPrompts.get_by_language(language)

    new_llm_role_definition = st.text_area(
        label="Custom System Prompt Context",
        value=system_prompt.llm_role_definition,
        height=200,
        help=(
            "The assistant is already guided with reasoning instructions and structured "
            "analysis steps tailored to the detected prompt type. Use this field to add "
            "extra context such as tone, domain expertise, brand voice, or audience targeting. "
            "This helps the assistant better reflect your specific use case or communication style."
        ),
    )

    updated_by = st.text_input(
        "Updated by",
        value=st.session_state.updated_by,
        placeholder="Your name or username",
        key="updated_by",
    )

    col_save, col_reset = st.columns(2)
    with col_save:
        if st.button("💾 Save Changes"):
            if not new_llm_role_definition.strip() or not updated_by.strip():
                st.error("Both fields are required.")
            else:
                SystemPrompts.update(
                    system_prompt.id,
                    llm_role_definition=new_llm_role_definition,
                    updated_by=updated_by,
                )
                st.session_state["just_saved"] = True
                st.rerun()
        if st.session_state.get("just_saved"):
            st.success("System prompt updated successfully.")
            del st.session_state["just_saved"]
    with col_reset:
        if st.button("🔄 Reset current LLM Instruction"):
            if not new_llm_role_definition.strip() or not updated_by.strip():
                st.error("Both fields are required.")
            else:
                SystemPrompts.reset(system_prompt.id, updated_by=updated_by)
                st.session_state["just_reset"] = True
                st.rerun()
        if st.session_state.get("just_reset"):
            st.success("Current prompt reset to default.")
            del st.session_state["just_reset"]

    with st.expander("📄 Information"):
        st.markdown(f"**Last updated by:** {system_prompt.updated_by}")
        humanized_updated_at = humanize_datetime(system_prompt.updated_at)
        st.markdown(f"**Last updated at:** {humanized_updated_at}")

    return updated_by


def prompt_page():
    st.set_page_config(
        page_title=get_standalone_interface_config().page_title,
        page_icon=get_standalone_interface_config().page_icon,
        layout="wide",
    )
    apply_omnirag_style()
    omnirag_header()
    init_prompt_session_state()
    st.title("🔧 System Prompt Customization")
    updated_by = update_section()
    st.markdown("---")
    reset_all_section(updated_by)


if __name__ == "__main__":
    prompt_page()
