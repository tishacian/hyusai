#!/bin/bash

set -e
cd -- "$(dirname "$0")" >/dev/null 2>&1
export LANG=C.UTF-8

OS_TYPE=$(uname)
PYTHON_VERSION='3.12'

updatePathBrew() {
	local BREW_INSTALL_DIR='/opt/homebrew/bin'
	if [[ ":$PATH:" != *":/usr/local/bin:"* ]]; then
		echo "PATH=$PATH:/usr/local/bin" >>"$HOME"/.bash_profile
		source "$HOME"/.bash_profile
	fi
	{
		type -P brew >/dev/null 2>&1
	} || {
		if [ ! -f "$BREW_INSTALL_DIR/brew" ]; then
			echo "brew not found"
			exit 1
		fi
		if [[ ":$PATH:" != *":$BREW_INSTALL_DIR:"* ]]; then
			echo "PATH=$PATH:$BREW_INSTALL_DIR" >>"$HOME"/.bash_profile
			source "$HOME"/.bash_profile
		fi
	}
}

getPkgManager() {
	set +e
	if [[ "$OS_TYPE" == "Darwin" ]]; then
		updatePathBrew
		echo "brew"
	elif [[ "$OS_TYPE" == "Linux" ]]; then
		source /etc/os-release
		case $ID in
		debian | ubuntu)
			echo "apt"
			;;
		*)
			echo "Unsupported Linux distribution: $ID."
			exit 1
			;;
		esac
	else
		echo "Unsupported OS: $OS_TYPE."
		exit 1
	fi
	set -e
}
PKG_MANAGER=$(getPkgManager)

install_python() {
	echo "Installing Python $PYTHON_VERSION"
	case $PKG_MANAGER in
	brew)
		brew install "python@$PYTHON_VERSION"
		;;
	apt)
		sudo -v
		sudo add-apt-repository ppa:deadsnakes/ppa
		sudo apt update
		sudo apt install "python$PYTHON_VERSION"
		;;
	*)
		echo "Unsupported package manager."
		exit 1
		;;
	esac
}

{
	set +e
	type -P "python$PYTHON_VERSION" >/dev/null 2>&1
	set -e
} || {
	echo "python$PYTHON_VERSION not found"
	install_python
}

echo "Creating virtual environment with Python $PYTHON_VERSION..."
eval "python$PYTHON_VERSION -m venv .venv"

echo "Activating virtual environment..."
# shellcheck source=.venv/bin/activate
source .venv/bin/activate

echo "Updating pip in virtual environment..."
python -m pip install --upgrade pip

echo "Installing Python venv in virtual environment..."
python -m pip install virtualenv

install_tesseract() {
	echo "Installing tesseract"
	case $PKG_MANAGER in
	brew)
		brew install tesseract --all-languages
		;;
	apt)
		sudo -v
		sudo apt update
		sudo apt install tesseract-ocr-all
		;;
	*)
		echo "Unsupported package manager."
		exit 1
		;;
	esac
}

# Install tesseract if not present
{
	set +e
	type -P tesseract >/dev/null 2>&1
	set -e
} || {
	echo "tesseract not found"
	install_tesseract
}

# Check for GPU availability and install appropriate requirements
echo "Checking GPU availability..."

if command -v nvidia-smi &> /dev/null; then
    echo "NVIDIA GPU detected"
    environment="gpu"
elif command -v nvcc &> /dev/null; then
    echo "CUDA detected"
    environment="gpu"
elif [[ "$OS_TYPE" == "Darwin" ]]; then
    if [[ $(uname -m) == "arm64" ]]; then
        echo "Apple Silicon (M1/M2) detected"
    else
        echo "Intel macOS detected"
    fi
    environment="macos"
else
    echo "No GPU detected, using CPU-only setup"
    environment="cpu"
fi

echo "Detected environment: $environment"

if [[ "$environment" == "gpu" ]]; then
    echo "Installing GPU requirements..."
    pip install -r requirements/shared.txt -r requirements/gpu.txt
    # Install PyTorch with CUDA 12.8 support
    pip install torch==2.7.0+cu128 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
elif [[ "$environment" == "macos" ]]; then
    echo "Installing macOS requirements..."
    pip install -r requirements/shared.txt -r requirements/cpu.txt
    # Install PyTorch with MPS support for Apple Silicon
    pip install torch torchvision torchaudio
elif [[ "$environment" == "cpu" ]]; then
    echo "Installing CPU requirements..."
    pip install -r requirements/shared.txt -r requirements/cpu.txt
    # Install PyTorch CPU version
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
else
    echo "Unknown environment, using CPU requirements..."
    pip install -r requirements/shared.txt -r requirements/cpu.txt
    # Install PyTorch CPU version
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
fi
