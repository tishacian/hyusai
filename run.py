import uvicorn

from configuration import rout_conf
from connections.fastapi.main import app

if __name__ == "__main__":
    uvicorn_config = rout_conf().uvicorn

    uvicorn_args = {
        "app": app,
        "host": uvicorn_config.host,
        "port": uvicorn_config.port,
        "log_level": uvicorn_config.log_level,
        "access_log": uvicorn_config.access_log,
    }

    uvicorn.run(**uvicorn_args)
