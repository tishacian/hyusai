#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/backend"

# Create .env if missing
if [ ! -f .env ]; then
    echo "Creating .env from .env.example"
    cp .env.example .env
    echo ">>> Please set OPENAI_API_KEY in backend/.env before running the demo <<<"
    exit 1
fi

# Create venv if missing
if [ ! -d "$ROOT/venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$ROOT/venv"
fi

source "$ROOT/venv/bin/activate"

echo "Installing dependencies..."
pip install -q -r requirements.txt

echo ""
echo "=== Starting AI Orchestration Platform ==="
echo "    Frontend: http://localhost:8000"
echo "    API:      http://localhost:8000/api/v1"
echo "    Docs:     http://localhost:8000/docs"
echo ""

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
