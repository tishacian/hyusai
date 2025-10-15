from connections.celery.db import init_celery_db
from connections.database import init_db

if __name__ == "__main__":
    init_celery_db()
    init_db()
    print("Database initialization complete.")
