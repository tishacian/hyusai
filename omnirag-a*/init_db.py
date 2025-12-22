#!/usr/bin/env python3
"""Initialize database by creating all tables"""
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.base import Base, engine
from app.models import User, Session, Message, Document, Agent, Task, AppSettings  # Import all models to register them

def init_db():
    """Create all database tables"""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully!")
    
    # Create default settings if they don't exist
    from app.db.base import SessionLocal
    from app.models.settings import AppSettings
    
    db = SessionLocal()
    try:
        existing = db.query(AppSettings).filter(AppSettings.id == "default").first()
        if not existing:
            default_settings = AppSettings(id="default")
            db.add(default_settings)
            db.commit()
            print("Default settings created!")
        else:
            print("Default settings already exist.")
    except Exception as e:
        print(f"Warning: Could not create default settings: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    try:
        init_db()
    except Exception as e:
        print(f"Error initializing database: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

