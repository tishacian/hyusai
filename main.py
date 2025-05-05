import os
import sys
import torch
from streamlit.web import cli as stcli
import warnings
from utils import get_username_from_path


torch.classes.__path__ = []
os.environ["CUDA_VISIBLE_DEVICES"] = "1" if torch.cuda.device_count() > 1 else "0"
os.environ["VLLM_WORKER_MULTIPROC_METHOD"] = "spawn"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
warnings.simplefilter(action="ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*deprecated.*")


if __name__ == "__main__":
    base_url_path = get_username_from_path()

    sys.argv = [
        "streamlit",
        "run",
        "src/ragger.py",
        "--server.port",
        "8508",
        "--server.baseUrlPath",
        base_url_path,
    ]
    sys.exit(stcli.main())
