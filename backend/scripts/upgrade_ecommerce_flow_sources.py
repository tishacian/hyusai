"""Review by default; --apply atomically publishes Luma sources and the Work pin."""

import argparse
import json

from app.db.base import SessionLocal
from app.models.user import User
from app.models.workspace import Workspace
from app.services.ecommerce_source_upgrade import upgrade


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--actor-user-id", required=True)
    parser.add_argument("--system-id", required=True)
    parser.add_argument("--expected-flow-sha256", required=True)
    parser.add_argument("--expected-release-id", required=True)
    parser.add_argument("--channel", choices=("pilot", "live"), default="live")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-target-sha256")
    args = parser.parse_args()
    with SessionLocal() as db:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).one()
        actor = db.query(User).filter(User.id == args.actor_user_id).one()
        result = upgrade(
            db,
            workspace,
            actor,
            system_id=args.system_id,
            expected_flow_sha256=args.expected_flow_sha256,
            expected_release_id=args.expected_release_id,
            channel=args.channel,
            apply=args.apply,
            expected_target_sha256=args.expected_target_sha256,
        )
        if args.apply:
            db.commit()
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
