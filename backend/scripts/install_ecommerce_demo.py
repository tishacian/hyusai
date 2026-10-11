"""Run in the deployed backend environment after the demo DB seed and source mapping.

No connection credentials accepted on the command line. The configured workspace
connector supplies the bounded reader's credentials. No seed runs automatically.
"""
import argparse
import json
import sys
from pathlib import Path
from app.db.base import SessionLocal
from app.models.user import User
from app.models.workspace import Workspace
from app.services.ecommerce_install import install


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--actor-user-id", required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--benchmark-protocol", type=Path)
    parser.add_argument("--payload-stdin", action="store_true")
    parser.add_argument("--collections", nargs="+", required=True)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    payload = json.load(sys.stdin) if args.payload_stdin else None
    if not payload and (not args.manifest or not args.benchmark_protocol):
        parser.error("Provide --payload-stdin or both manifest and benchmark protocol paths")
    manifest = payload["manifest"] if payload else json.loads(args.manifest.read_text())
    policy = next(r for r in manifest["documents"] if r["reference"] == "refund-policy-v2")
    benchmark = payload["benchmark_protocol"] if payload else json.loads(args.benchmark_protocol.read_text())
    with SessionLocal() as db:
        workspace = db.query(Workspace).filter(Workspace.slug == args.workspace).one()
        actor = db.query(User).filter(User.id == args.actor_user_id).one()
        result = install(db, workspace, actor, policy_sha256=policy["sha256"], source_collections=args.collections, benchmark=benchmark, activate=args.activate)
        db.commit(); print(json.dumps(result, indent=2))


if __name__ == "__main__": main()
