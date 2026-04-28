#!/bin/bash
set -e

: "${RESOURCES_TESSDATA:?RESOURCES_TESSDATA must be set}"

if [ -d "$RESOURCES_TESSDATA" ] && [ "$(ls -A "$RESOURCES_TESSDATA")" ]; then
	echo "Tesseract languages already installed, skipping."
	exit 0
fi

echo "Installing Tesseract OCR and all languages..."
apt-get update &&
	apt-get install --no-install-recommends -y tesseract-ocr-all &&
	rm -rf /var/lib/apt/lists/*

mkdir -p "$RESOURCES_TESSDATA"
cp -r /usr/share/tesseract-ocr/5/tessdata/* "$RESOURCES_TESSDATA"

echo "Tesseract languages installed successfully."
