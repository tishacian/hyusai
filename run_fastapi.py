import uvicorn

from configurations import rout_conf
from connections.fastapi.main import app

if __name__ == "__main__":
    router_config = rout_conf()
    router_config.logging.setup()
    uvicorn.run(app, **router_config.uvicorn.model_dump())
