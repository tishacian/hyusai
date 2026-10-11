"""Seed script — creates a default workspace and assigns the first admin user as owner.

Usage:
    cd backend && python -m scripts.seed_workspace
"""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.base import SessionLocal, engine, Base
from app.models.workspace import Workspace, WorkspaceMember
from app.models.user import User
import app.models  # noqa: F401 — register all models


def seed():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.slug == "default").first()
        if ws:
            print(f"Workspace 'default' already exists (id={ws.id})")
        else:
            ws = Workspace(id=str(uuid4()), name="Default", slug="default")
            db.add(ws)
            db.commit()
            db.refresh(ws)
            print(f"Created workspace 'default' (id={ws.id})")

        admin = db.query(User).filter(User.role == "admin").first()
        if not admin:
            admin = db.query(User).first()
        if not admin:
            admin = User(
                id=str(uuid4()),
                username="admin",
                email="admin@agentium.local",
                role="admin",
                is_active=True,
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)
            print(f"Created admin user (id={admin.id})")

        existing = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == admin.id, WorkspaceMember.workspace_id == ws.id)
            .first()
        )
        if existing:
            print(f"User '{admin.username}' is already a member of 'default'")
        else:
            membership = WorkspaceMember(user_id=admin.id, workspace_id=ws.id, role="owner")
            db.add(membership)
            db.commit()
            print(f"Added '{admin.username}' as owner of 'default'")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
