import os
import sys
from pathlib import Path

import uvicorn

if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(repo_root / "backend"))

    host = os.getenv("HOST", os.getenv("UVICORN_HOST", "0.0.0.0"))
    port = int(os.getenv("PORT", os.getenv("UVICORN_PORT", "8000")))
    log_level = os.getenv("LOG_LEVEL", os.getenv("UVICORN_LOG_LEVEL", "info")).lower()

    uvicorn.run("app.main:app", host=host, port=port, log_level=log_level)
