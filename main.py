import sys

from streamlit.web import cli as stcli

if __name__ == "__main__":
    sys.argv = [
        "streamlit",
        "run",
        "src/rag_chatbot.py",
        "--server.port",
        "8508",
    ]
    sys.exit(stcli.main())
