import uvicorn

from configurations import rout_conf
from connections.celery.db import init_celery_db
from connections.fastapi.main import app
from src.db import init_db

if __name__ == "__main__":
    init_celery_db()
    init_db()
    router_config = rout_conf()
    router_config.logging.setup()
    uvicorn.run(app, **router_config.uvicorn.model_dump())
