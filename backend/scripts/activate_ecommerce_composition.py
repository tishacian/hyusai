"""Activate the reviewed Luma composition; review is the default operation."""

import argparse
import json
import sys

from app.db.base import SessionLocal
from app.models.user import User
from app.models.workspace import Workspace
from app.services.ecommerce_composition_upgrade import upgrade


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--actor-user-id", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-composition-sha256")
    args = parser.parse_args()
    plan = json.load(sys.stdin)
    with SessionLocal() as db:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).one()
        actor = db.query(User).filter(User.id == args.actor_user_id).one()
        result = upgrade(
            db,
            workspace,
            actor,
            plan=plan,
            apply=args.apply,
            expected_composition_sha256=args.expected_composition_sha256,
        )
        if args.apply:
            db.commit()
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
