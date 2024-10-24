#!/bin/bash

# Installing python3
echo "Installing python3.12..."
sudo apt install python3.12 -y
echo "PATH = $PATH:$HOME/.local/bin" >> ~/.bashrc

# Updating pip
echo "Updating pip..."
pip3 install --upgrade pip

# Installing venv
echo "Installing Python venv..."
sudo apt install python3.12-venv -y

# Creating environment
echo "Creating environment..."
python3.12 -m venv .venv

# Activating environment
echo "Activating environment..."
source .venv/bin/activate

# -- check for cuda
if command -v nvidia-smi &> /dev/null; then
    echo "CUDA detected. Installing GPU requirements..."
    pip3 install -r requirements/requirements_gpu.txt
else
    echo "CUDA not detected. Installing CPU requirements..."
    pip3 install -r requirements/requirements_cpu.txt
fi

echo "Installation complete."
