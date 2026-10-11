"""Stream public synthetic manifests/protocol to the deployed operator CLI."""
import json
from pathlib import Path
root = Path(__file__).resolve().parent
print(json.dumps({"manifest": json.loads((root / "manifest.json").read_text()),
                  "benchmark_manifest": json.loads((root / "benchmark/manifest.json").read_text()),
                  "benchmark_protocol": json.loads((root / "benchmark/protocol.json").read_text())}, ensure_ascii=False))
