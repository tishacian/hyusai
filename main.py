import os
import sys
import torch
import platform
import socket
from streamlit.web import cli as stcli
import warnings
from src.globalvariables import Ports

torch.classes.__path__ = []
os.environ["CUDA_VISIBLE_DEVICES"] = (
    "1" if torch.cuda.device_count() > 1 else "0"
)
os.environ["VLLM_WORKER_MULTIPROC_METHOD"] = "spawn"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
warnings.simplefilter(action="ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*deprecated.*")


def get_username_from_path():
    """
    Extract username from current working directory path.
    """
    cwd = os.getcwd()
    system = platform.system().lower()
    path_parts = cwd.replace("\\", "/").split("/")
    # -- handle different platforms
    jupyter_user = next(
        (
            part.replace("jupyter-", "")
            for part in path_parts
            if part.startswith("jupyter-")
        ),
        None,
    )
    if jupyter_user:
        return jupyter_user

    if system == "windows":
        if "Users" in path_parts:
            idx = path_parts.index("Users")
            if idx + 1 < len(path_parts):
                return path_parts[idx + 1]
    elif system in ["darwin", "linux"]:
        user_dirs = ["Users", "home"]
        for dir_name in user_dirs:
            if dir_name in path_parts:
                idx = path_parts.index(dir_name)
                if idx + 1 < len(path_parts):
                    return path_parts[idx + 1]

    try:
        return os.getlogin()
    except:
        return None


def available_port(
    start_port=8501, end_port=8509
):
    """Find an available port and return None if not available

    Parameters
    ----------
    start_port : int, optional
        Default starting port. The default is 8509.
    end_port : int, optional
        End port search here. The default is 8520.

    Returns
    -------
    int or None
        Available port number, or None if no port is available within the range.
    """
    for port in range(start_port, end_port + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("", port))
                return port
        except OSError:
            continue

    return None


if __name__ == "__main__":
    base_url_path = get_username_from_path()
    port = available_port()

    if port is None:
        sys.exit(1)

    sys.argv = [
        "streamlit",
        "run",
        "src/ragger.py",
        "--server.port",
        str(port),
        "--server.baseUrlPath",
        base_url_path,
    ]
    sys.exit(stcli.main())
