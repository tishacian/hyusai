#!/bin/bash

# Determine the OS type
OS_TYPE=$(uname)
IS_WINDOWS=false
IS_WSL=false

if [[ "$OS_TYPE" == "Darwin" ]]; then
    echo "OS detected: macOS"
    PACKAGE_MANAGER="brew"
elif [[ "$OS_TYPE" == "Linux" ]]; then
    if grep -qi microsoft /proc/version; then
        echo "OS detected: Windows Subsystem for Linux (WSL)"
        IS_WSL=true
    else
        echo "OS detected: Linux"
    fi
    PACKAGE_MANAGER="apt"
else
    echo "OS detected: Windows (assuming Git Bash or WSL)"
    IS_WINDOWS=true
    PACKAGE_MANAGER="choco"
fi

# install Python 3.11
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

# -- Check for CUDA (assuming nvidia-smi for CUDA detection)
if command -v nvidia-smi &> /dev/null; then
    echo "CUDA detected. Installing GPU requirements..."
    pip install -r requirements/requirements_gpu.txt
else
    echo "CUDA not detected. Installing CPU requirements..."
    if [[ "$OS_TYPE" == "Darwin" || "$IS_WINDOWS" == true ]]; then
        echo "Running on macOS or Windows. Skipping incompatible packages like vLLM..."
        # Create a filtered requirements file without vLLM if running on macOS or Windows
        grep -v "vllm==" requirements/requirements_cpu.txt > temp_requirements.txt
        pip install -r temp_requirements.txt
        rm temp_requirements.txt
    else
        echo "Attempting to install all requirements including vLLM..."
        pip install -r requirements/requirements_cpu.txt || {
            echo "vLLM installation failed. Trying to install without vLLM..."
            grep -v "vllm==" requirements/requirements_cpu.txt > temp_requirements.txt
            pip install -r temp_requirements.txt
            rm temp_requirements.txt
        }
    fi
fi

echo "Installation complete."
