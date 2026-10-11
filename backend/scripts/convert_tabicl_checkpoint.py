#!/usr/bin/env python3
"""Convert an operator-acquired, pinned TabICLv2 checkpoint offline.

Publish the result through the existing signed offline HF artifact workflow;
this command neither grants workspace access nor activates a model.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.resources.ml_tabicl_runtime import convert_checkpoint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--task", required=True, choices=("classification", "regression"))
    args = parser.parse_args()
    print(
        json.dumps(
            convert_checkpoint(args.source, args.destination, task=args.task), sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
