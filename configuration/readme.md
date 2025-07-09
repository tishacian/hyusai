# Environment configuration

The python ragger service can be configured through environment variables.

On DevOps' side, default values should be the production environment values. These default values will be overidden for non production environments.

Note that the default values in this document are those set on python side. They reflect the values of a development environment.

## Available Configurations

### General

- `IS_STANDALONE` (bool)
    - If True, the service will be accessible through a customizable RAG webapp.
    - By default `True`

### Backend

- `DISABLE_OCR_FOR_PDF` (bool)
    - If True, OCR won't be available when processing PDF documents.
    - By default `False`
- `FORCE_OCR_ON_ALL_PDF` (bool)
    - If True, OCR will be applied to all PDF documents, even text-based documents, ignoring the digital text content.
    `disable_ocr_for_pdf` is expected to be `False` when using this variable.
    - By default `False`

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
    - By default `"https://media.glassdoor.com/sql/3258770/datategy-squarelogo-1664441768173.png"`
- `PAGE_TITLE` (str)
    - The page title.
    - By default `"OmniRAG"`
- `PAGE_TITLE` (str)
    - The header title.
    - By default `"OmniRAG"`
- `AI_CHAT_LOGO` (str)
    - Path of the AI chatbot logo in the chat.
    - By default `"image/datategy_logo.png"`
- `HUMAN_CHAT_LOGO` (str)
    - Path of the human user logo in the chat.
    - By default `"image/aitubo.jpg"`
- `HIDE_RAG_PARAMS_CONFIG` (bool)
    - If True, the section where the user parametrized the RAG steps will be hidden.
    - By default `False`
- `FORCED_VDB` (str)
    - Force the RAG to use the provided Vector DataBase as context (the section where the 
    user parametrize the RAG steps per consequent).
    If `"None"`, the user will be asked to create/select the desired Vector DataBase.
    - By default `"None"`
- `DEFAULT_GPU_MODEL` (str)
    - Default GPU model.
    - By default `"neuralmagic/Meta-Llama-3.1-8B-Instruct-quantized.w4a16"`
- `COOKIE_NAME` (str)
    - Name of the authentification cookie.
    - By default `omnirag_auth`
- `COOKIE_KEY` (str)
    - Secret key for the authentification cookie.
    Consider setting this to a set value using a private .env file to fully benefit from
    the authentification cookie after restart.
    - By default `secrets.token_hex(32)`
- `COOKIE_EXPIRY_DAYS` (int)
    - Number of days the authentification cookie will be valid.
    - By default `1`
