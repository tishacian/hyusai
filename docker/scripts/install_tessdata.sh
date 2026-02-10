#!/bin/bash
set -e

if [ -d "$PAPAILLM_RESSOURCES__TESSDATA" ] && [ "$(ls -A "$PAPAILLM_RESSOURCES__TESSDATA")" ]; then
	echo "Tesseract languages already installed, skipping."
	exit 0
fi

echo "Installing Tesseract OCR and all languages..."
apt-get update &&
	apt-get install --no-install-recommends -y tesseract-ocr-all &&
	rm -rf /var/lib/apt/lists/*

mkdir -p "$PAPAILLM_RESSOURCES__TESSDATA"
cp -r /usr/share/tesseract-ocr/5/tessdata/* "$PAPAILLM_RESSOURCES__TESSDATA"

echo "Tesseract languages installed successfully."
