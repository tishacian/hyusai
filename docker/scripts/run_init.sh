#!/bin/bash
set -e

echo "Running initialization..."

bash /app/docker/scripts/install_tessdata.sh

export PYTHONPATH=/app
python3.12 /app/docker/scripts/init_dbs.py

echo "Initialization finished."
