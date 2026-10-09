#!/usr/bin/env python3
"""Render least-privilege MinIO policies; installation is an operator action.

Replacing the historical bucket-wide application policy is required: attaching
a narrower second policy cannot revoke the first one's grants. Explicit Deny
also protects the Hub model/staging prefixes if an old grant was left attached.
No principal, credential, bucket or server is modified by this renderer.
"""

from __future__ import annotations

import argparse
import json
import re


def policies(bucket: str) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
        raise ValueError("Use a valid explicit S3 bucket name")
    resource = f"arn:aws:s3:::{bucket}"

    def statement(actions, suffixes, *, effect="Allow", condition=None):
        result = {
            "Effect": effect,
            "Action": actions,
            "Resource": [resource + suffix for suffix in suffixes],
        }
        if condition:
            result["Condition"] = condition
        return result

    location = statement(["s3:GetBucketLocation"], [""])
    list_hub = statement(
        ["s3:ListBucket", "s3:ListBucketVersions", "s3:ListBucketMultipartUploads"],
        [""],
        condition={"StringLike": {"s3:prefix": ["hub/", "hub/*"]}},
    )
    return {
        "hub-fetch": {
            "Version": "2012-10-17",
            "Statement": [
                location,
                list_hub,
                statement(
                    [
                        "s3:GetObject",
                        "s3:PutObject",
                        "s3:AbortMultipartUpload",
                        "s3:ListMultipartUploadParts",
                        "s3:DeleteObject",
                        "s3:DeleteObjectVersion",
                    ],
                    ["/hub/*"],
                ),
            ],
        },
        "hub-read": {
            "Version": "2012-10-17",
            "Statement": [
                location,
                statement(["s3:GetObject"], ["/hub/artifacts/*", "/hub/blobs/*"]),
            ],
        },
        "application": {
            "Version": "2012-10-17",
            "Statement": [
                location,
                statement(["s3:ListBucket"], [""]),
                statement(
                    [
                        "s3:GetObject",
                        "s3:PutObject",
                        "s3:AbortMultipartUpload",
                        "s3:ListMultipartUploadParts",
                    ],
                    ["/*"],
                ),
                statement(
                    [
                        "s3:PutObject",
                        "s3:AbortMultipartUpload",
                        "s3:DeleteObject",
                        "s3:DeleteObjectVersion",
                    ],
                    ["/hub/blobs/*", "/hub/tmp/*"],
                    effect="Deny",
                ),
                statement(
                    ["s3:DeleteObject", "s3:DeleteObjectVersion"], ["/*"], effect="Deny"
                ),
            ],
        },
        "tabular-purge": {
            "Version": "2012-10-17",
            "Statement": [
                location,
                statement(
                    ["s3:ListBucket", "s3:ListBucketVersions"],
                    [""],
                    condition={
                        "StringLike": {
                            "s3:prefix": ["workspaces/*/tabular/hub-artifacts/*"]
                        }
                    },
                ),
                statement(
                    ["s3:GetObject", "s3:DeleteObject", "s3:DeleteObjectVersion"],
                    ["/workspaces/*/tabular/hub-artifacts/*"],
                ),
            ],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument(
        "--role",
        required=True,
        choices=["hub-fetch", "hub-read", "application", "tabular-purge"],
    )
    args = parser.parse_args()
    print(json.dumps(policies(args.bucket)[args.role], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
