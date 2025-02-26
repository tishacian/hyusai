import sys

from streamlit.web import cli as stcli

if __name__ == "__main__":
    sys.argv = [
        "streamlit",
        "run",
        "src/ragger.py",
        "--server.port",
        "8509",
    ]
    sys.exit(stcli.main())
