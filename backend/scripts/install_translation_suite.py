"""Install the self-hosted Translation Suite into one workspace.

Run in the deployed backend environment once the workspace has an external
runner (``/api/v1/remote-runners``) allowed to run the ``translation_suite.*``
commands and labelled with the pipeline paths. Nothing runs automatically.

    python scripts/install_translation_suite.py --workspace agentium-showcase \
        --actor-user-id <owner id> --runner gpu-vm [--activate] \
        [--certify-profile certify_profile.json]

``--certify-profile`` adds the golden certification step after packaging; the
file is the ``ts.runner certify`` profile (paths on the runner).
"""

import argparse
import json
from pathlib import Path

from app.db.base import SessionLocal
from app.models.user import User
from app.models.workspace import Workspace
from app.services.translation_suite.install import install


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, help="Workspace slug.")
    parser.add_argument("--actor-user-id", required=True)
    parser.add_argument("--runner", required=True, help="Slug of the workspace's external runner.")
    parser.add_argument("--activate", action="store_true", help="Deploy the review app live.")
    parser.add_argument("--certify-profile", type=Path, default=None)
    args = parser.parse_args()
    profile = (
        json.loads(args.certify_profile.read_text(encoding="utf-8"))
        if args.certify_profile
        else None
    )
    with SessionLocal() as db:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).one()
        actor = db.query(User).filter(User.id == args.actor_user_id).one()
        result = install(
            db,
            workspace,
            actor,
            runner_slug=args.runner,
            activate=args.activate,
            certify_profile=profile,
        )
        db.commit()
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
