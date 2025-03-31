# Environment configuration

The python ragger service can be configured through environment variables.

On DevOps' side, default values should be the production environment values. These default values will be overidden for non production environments.

Note that the default values in this document are those set on python side. They reflect the values of a development environment.

## Available Configurations

### General

- `IS_STANDALONE` (bool)
    - If True, the service will be accessible through a customizable RAG webapp.
    - By default `True`

### Standalone Interface

Standalone Interface is only available if `IS_STANDALONE` is set to `True`.

- `PAGE_ICON` (str)
    - The page favicon.
    In addition to the types supported by st.image (like URLs), the following strings are valid: 
        - A single-character emoji. For example, you can set page_icon="🦈".
        - An emoji short code. For example, you can set page_icon=":shark:". For a list of all supported codes, see https://share.streamlit.io/streamlit/emoji-shortcodes.
        - The string literal, "random". You can set page_icon="random" to set a random emoji from the supported list above. Emoji icons are courtesy of Twemoji and loaded from MaxCDN.
        - An icon from the Material Symbols library (outlined style) in the format ":material/icon_name:" where "icon_name" is the name of the icon in snake case.
    For example, icon=":material/thumb_up:" will display the Thumb Up icon. Find additional icons in the Material Symbols font library.
    - By default `https://media.glassdoor.com/sql/3258770/datategy-squarelogo-1664441768173.png`
- `PAGE_TITLE` (str)
    - The page title..
    - By default `RAGGER`
- `AI_CHAT_LOGO` (str)
    - Path of the AI chatbot logo in the chat.
    - By default `image/datategy_logo.png`
- `HUMAN_CHAT_LOGO` (str)
    - Path of the human user logo in the chat.
    - By default `image/aitubo.jpg`
- `HIDE_RAG_PARAMS_CONFIG` (bool)
    - If True, the section where the user parametrized the RAG steps will be hidden.
    - By default `False`
- `FORCED_VDB` (str)
    - Force the RAG to use the provided Vector DataBase as context (the section where the 
    user parametrize the RAG steps per consequent).
    If `"None"`, the user will be asked to create/select the desired Vector DataBase.
    - By default `"None"`
