import base64
from io import BytesIO

import streamlit as st
from PIL import Image

from configuration import get_standalone_interface_config


def load_avatar(image_path):
    return Image.open(image_path).resize((128, 128))


def image_to_base64(image):
    buffered = BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()


HUMAN_AVATAR_PATH = get_standalone_interface_config().human_chat_logo
AI_AVATAR_PATH = get_standalone_interface_config().ai_chat_logo

HUMAN_AVATAR = load_avatar(HUMAN_AVATAR_PATH)
AI_AVATAR = load_avatar(AI_AVATAR_PATH)

HUMAN_AVATAR_B64 = image_to_base64(HUMAN_AVATAR)
AI_AVATAR_B64 = image_to_base64(AI_AVATAR)


def omnirag_header():
    st.markdown(
        f"""
        <div class="app-header">
            <img src="data:image/png;base64,{AI_AVATAR_B64}" alt="AI Avatar"/>
            <h1>{get_standalone_interface_config().header_title}</h1>
        </div>
    """,
        unsafe_allow_html=True,
    )
