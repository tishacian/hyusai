#!/bin/bash
set -e

ASSETS_DIR="/data/assets/tessdata"

if [ -d "$ASSETS_DIR" ] && [ "$(ls -A "$ASSETS_DIR")" ]; then
    echo "Tesseract languages already installed, skipping."
    exit 0
fi

echo "Installing Tesseract OCR and all languages..."
apt-get update \
    && apt-get install --no-install-recommends -y tesseract-ocr-all \
    && rm -rf /var/lib/apt/lists/*

mkdir -p "$ASSETS_DIR"
cp -r /usr/share/tesseract-ocr/5/tessdata/* "$ASSETS_DIR"

echo "Tesseract languages installed successfully."
