import uvicorn
from common_config.uvicorn import UvicornConfig

from connections.fastapi.main import app

if __name__ == "__main__":
    config = UvicornConfig()

    uvicorn_args = {
        "app": app,
        "host": config.host,
        "port": config.port,
        "log_level": config.log_level,
        "access_log": config.access_log,
    }

    uvicorn.run(**uvicorn_args)
