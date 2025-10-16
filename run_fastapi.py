import uvicorn

from configurations import Config
from connections.fastapi.main import app

if __name__ == "__main__":
    router_config = Config.get()
    router_config.logging.setup()
    uvicorn.run(app, **router_config.fastapi_server.model_dump())
