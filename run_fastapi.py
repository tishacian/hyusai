import uvicorn

from configurations import FastAPIConfig
from connections.fastapi.main import app

if __name__ == "__main__":
    config = FastAPIConfig.get()
    config.logging.setup()
    uvicorn.run(app, **config.server.model_dump())
