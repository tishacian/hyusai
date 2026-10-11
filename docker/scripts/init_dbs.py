def init_agentium_db() -> None:
    from app.db.base import Base, engine
    import app.models  # noqa: F401  register SQLAlchemy models

    Base.metadata.create_all(bind=engine)


def init_legacy_db_best_effort() -> None:
    try:
        from connections.celery.db import init_celery_db
        from connections.database import init_db
    except Exception as exc:  # noqa: BLE001
        print(f"Skipping legacy DB initialization: {exc}")
        return

    init_celery_db()
    init_db()


if __name__ == "__main__":
    init_agentium_db()
    init_legacy_db_best_effort()
    print("Database initialization complete.")
