#!/bin/bash

# Determine the OS type
OS_TYPE=$(uname)
IS_WINDOWS=false
IS_WSL=false

if [[ "$OS_TYPE" == "Darwin" ]]; then
    echo "OS detected: macOS"
    PLATFORM="Darwin"
    PACKAGE_MANAGER="brew"
elif [[ "$OS_TYPE" == "Linux" ]]; then
    if grep -qi microsoft /proc/version; then
        echo "OS detected: Windows Subsystem for Linux (WSL)"
        IS_WSL=true
        PLATFORM="Linux"
    else
        echo "OS detected: Linux"
        PLATFORM="Linux"
    fi
    PACKAGE_MANAGER="apt"
else
    echo "OS detected: Windows (assuming Git Bash or WSL)"
    IS_WINDOWS=true
    PLATFORM="Windows"
    PACKAGE_MANAGER="choco"
fi

# Exit if platform not supported
if [[ "$PLATFORM" != "Windows" && "$PLATFORM" != "Darwin" && "$PLATFORM" != "Linux" ]]; then
    echo "Unsupported platform: $PLATFORM"
    exit 1
fi

# Install Python 3.11
install_python() {
    if [[ "$IS_WINDOWS" == true ]]; then
        echo "Checking for Chocolatey..."
        if ! command -v choco &> /dev/null; then
            echo "Chocolatey not found. Please install Chocolatey from https://chocolatey.org/."
            exit 1
        fi
        echo "Installing Python 3.11 using Chocolatey..."
        choco install python --version 3.11 -y
    else
        if [[ "$PACKAGE_MANAGER" == "brew" ]]; then
            echo "Installing Python 3.11 using Homebrew..."
            brew install python@3.11
        elif [[ "$PACKAGE_MANAGER" == "apt" ]]; then
            echo "Installing Python 3.11 using APT..."
            sudo apt install python3.11 -y
        fi
    fi
}

# Install Python if not present
if ! python3.11 --version &> /dev/null; then
    install_python
else
    echo "Python 3.11 already installed."
fi

# Updating PATH for macOS if necessary
if [[ "$OS_TYPE" == "Darwin" ]]; then
    echo "Updating PATH for macOS..."
    echo "PATH=$PATH:/usr/local/bin:/opt/homebrew/bin" >> ~/.bash_profile
    source ~/.bash_profile
fi

echo "Updating pip..."
python3.11 -m pip install --upgrade pip

echo "Installing Python venv..."
python3.11 -m pip install virtualenv

echo "Creating environment..."
python3.11 -m virtualenv .venv

echo "Activating environment..."
if [[ "$IS_WINDOWS" == true ]]; then
    source .venv/Scripts/activate
else
    source .venv/bin/activate
fi

# Install core requirements from requirements.txt
echo "Installing core requirements..."
pip install -r requirements/requirements.txt

# -- Check for CUDA (assuming nvidia-smi for CUDA detection)
if command -v nvidia-smi &> /dev/null; then
    echo "CUDA detected. Installing GPU-specific packages..."
    pip install vllm psutil
else
    echo "CUDA not detected. Installing CPU-specific packages..."
    pip install llama_cpp_python huggingface-hub
fi

# Install additional requirements for document processing
echo "Installing document processing requirements..."
pip install "unstructured[all-docs]"

# Install Tesseract OCR
if [[ "$PACKAGE_MANAGER" == "brew" ]]; then
    brew install tesseract
elif [[ "$PACKAGE_MANAGER" == "apt" ]]; then
    sudo apt install tesseract-ocr
fi
pip install tesserocr
pip install pytesseract

# -- installing tesseract language datasets..
LANGUAGES="eng fra deu spa ita por kor ara"
USER_TESSDATA="$HOME/.local/share/tessdata"
mkdir -p "$USER_TESSDATA"

echo "Installing language files to $USER_TESSDATA"
for lang in $LANGUAGES; do
    echo "Downloading $lang.traineddata..."
    if command -v wget &>/dev/null; then
        wget -q -O "$USER_TESSDATA/$lang.traineddata" "https://github.com/tesseract-ocr/tessdata/raw/main/$lang.traineddata"
    elif command -v curl &>/dev/null; then
        curl -s -L -o "$USER_TESSDATA/$lang.traineddata" "https://github.com/tesseract-ocr/tessdata/raw/main/$lang.traineddata"
    else
        echo "Neither wget nor curl found. Please install one of them."
        exit 1
    fi
    
    [ -f "$USER_TESSDATA/$lang.traineddata" ] && echo "✓ $lang" || echo "✗ $lang failed"
done

# Set environment variables
export TESSDATA_PREFIX="$USER_TESSDATA"

# Add environment variable to shell profile
RC_FILE=""
if [[ "$PLATFORM" == "Darwin" ]]; then
    RC_FILE="$HOME/.bash_profile"
elif [[ "$PLATFORM" == "Linux" ]]; then
    RC_FILE="$HOME/.bashrc"
fi

if [[ -n "$RC_FILE" && -f "$RC_FILE" ]]; then
    grep -q "TESSDATA_PREFIX" "$RC_FILE" || echo "export TESSDATA_PREFIX=\"$USER_TESSDATA\"" >> "$RC_FILE"
    echo "Environment variable set in $RC_FILE"
fi

echo "Installation complete. TESSDATA_PREFIX=$USER_TESSDATA"
echo "Installation complete..All packages installed"