import sys
from streamlit.web import cli as stcli
import warnings

warnings.simplefilter(action="ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*deprecated.*")


if __name__ == "__main__":
    sys.argv = [
        "streamlit",
        "run",
        "src/ragger.py",
        "--server.port",
        "8509",
    ]
    sys.exit(stcli.main())
