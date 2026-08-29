"""Local HTTP fixture for the seven PR→PO MCP tools.

    python -m scripts.mcp_fixture_server
    python -m scripts.mcp_fixture_server --host 127.0.0.1 --port 8765

JSON-RPC POST /sap and POST /hikma. Used when MCP_FIXTURE=1 and live URLs
are absent.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.connectors.mcp.fixture import serve


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    httpd = serve(args.host, args.port)
    print(f"MCP fixture listening on http://{args.host}:{args.port}/sap and /hikma")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("fixture stopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
