#!/usr/bin/env python3
"""Run database migrations"""
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from alembic.config import Config
from alembic import command
from app.core.config import settings

def run_migrations():
    """Run all pending migrations"""
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
    
    print(f"Running migrations on database: {settings.database_url}")
    command.upgrade(alembic_cfg, "head")
    print("Migrations completed successfully!")

if __name__ == "__main__":
    try:
        run_migrations()
    except Exception as e:
        print(f"Error running migrations: {e}", file=sys.stderr)
        sys.exit(1)

