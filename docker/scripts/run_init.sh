#!/bin/bash
set -e

echo "Running initialization..."

bash /app/docker/scripts/install_tessdata.sh
python3.12 /app/docker/scripts/download_assets.py
python3.12 /app/docker/scripts/download_models.py
python3.12 /app/docker/scripts/init_dbs.py

echo "Initialization finished."
