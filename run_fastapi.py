import uvicorn

from configurations import Config
from connections.celery.db import init_celery_db
from connections.database import init_db
from connections.fastapi.main import app

if __name__ == "__main__":
    init_celery_db()
    init_db()
    router_config = Config.get()
    router_config.logging.setup()
    uvicorn.run(app, **router_config.fastapi_server.model_dump())
