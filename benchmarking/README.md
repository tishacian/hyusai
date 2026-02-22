# README #

This directory contains benchmarking scripts and utilities for evaluating RAG pipelines, specifically designed for multi-hop reasoning tasks. A detailed report is also available for internal use only.

### What is this repository for? ###

* Quick summary
* Version
* [Learn Markdown](https://bitbucket.org/tutorials/markdowndemo)

### How do I get set up? ###

For security reasons, you must clone this repo using an SSH key. You can follow [this guide](https://support.atlassian.com/bitbucket-cloud/docs/configure-ssh-and-two-step-verification/) from Atlassian to generate and add the SSH key to your account.

Once set up, you can safely clone this repository on your computer.

```
git clone —-branch bench/benchmark git@bitbucket.org:neuropolisteam/rag.git
```

#### Folder structure
The arrangment of files in the benchmarking folder

```
📜 benchmarking
├── 📄 README.md
├── 📜 benchmarking.py
├── 📜 customchain_hah.py
├── 📜 customchain_hybrid.py
├── 📜 customchain_naive.py
├── 📜 extrametrics.py
├── 📂 requirements
│   └── 📄 requirements.txt
└── 📜 resourcemonitor.py
```


## Setup Instructions

### Quick Setup
```bash
# Make install script executable
chmod +x install.sh

# Run installation (automatically detects GPU/CPU)
./install.sh
```

### Manual Setup
```bash
# Create virtual environment
python3 -m venv .venv

# Activate environment
source .venv/bin/activate

# Install dependencies based on your system:
# For macOS (Apple Silicon or Intel):
pip install -r requirements/macos.txt

# For GPU (NVIDIA/CUDA):
pip install -r requirements/gpu.txt
pip install -r requirements/shared.txt

# For CPU (Linux/Windows):
pip install -r requirements/cpu.txt
pip install -r requirements/shared.txt
```

## Available Scripts

### 1. `benchmarking.py`
- Evaluates naive RAG pipeline
- Uses fallback import system for compatibility
- Evaluates on multiple multi-hop reasoning datasets

### 2. `benchmarking-o1.py`
- Evaluates HAH (Hybrid Attention and Hierarchical) pipeline
- Includes comprehensive resource monitoring
- CO2 emissions tracking and cost calculation

### 3. `dataset_manager.py`
- Centralized dataset configuration and management
- Multi-hop reasoning specific dataset loading with caching
- Proper QA pair extraction for complex reasoning tasks
- Disk space monitoring and sample size control

## Usage

### Basic Benchmarking
```bash
# Activate environment
source .venv/bin/activate

# Run naive pipeline evaluation
python benchmarking.py

# Run HAH pipeline evaluation
python benchmarking-o1.py
```

### Environment Variables
```bash
# Set country code for CO2 emissions calculation
export COUNTRY_CODE="FR"  # France
export COUNTRY_CODE="US"  # United States
export COUNTRY_CODE="DE"  # Germany
```

## Dataset Information

### Multi-Hop Reasoning Datasets

#### HotpotQA
- **Purpose**: Multi-hop reasoning with supporting facts
- **Format**: Question + Answer + Supporting Facts
- **Use Case**: Complex reasoning requiring multiple information sources

#### 2WikiMultiHop
- **Purpose**: Multi-hop reasoning with Wikipedia articles
- **Format**: Question + Answer + Supporting Facts
- **Use Case**: Knowledge-intensive multi-hop reasoning

#### AmbigQA
- **Purpose**: Ambiguous questions requiring multi-hop reasoning
- **Format**: Question + Multiple Possible Answers
- **Use Case**: Handling ambiguity in complex reasoning tasks

#### CommonsenseQA
- **Purpose**: Commonsense reasoning with multiple choice
- **Format**: Question + Choices + Answer Key
- **Use Case**: Commonsense knowledge integration

## Output Structure

Results are saved to:
- `evaluation_results/` for naive pipeline
- `evaluation_results-o1/` for HAH pipeline

Each dataset gets its own subdirectory with:
- Metrics over time
- Resource usage metrics
- Cost calculations
- Summary statistics

## Troubleshooting

### Import Errors
If you encounter import errors:
1. Ensure you're in the benchmarking directory
2. Run `./setup_benchmarking.sh` to set up the environment
3. Check that all required modules are available

### Dataset Loading Issues
If datasets fail to load:
1. Check internet connection
2. Verify Hugging Face access
3. Some datasets may require authentication

### Resource Monitoring Issues
If resource monitoring fails:
1. Ensure `psutil` and `GPUtil` are installed
2. Check system permissions for resource access
3. GPU monitoring requires CUDA-compatible setup

## Average Evaluation Metrics of different RAG Methods

| Metric | HAH RAG | Hybrid RAG | Naive RAG |
|--------|---------|------------|------------|
| Latency (s) | **4.47 ± 2.28** | 12.60 ± 5.27 | 12.25 ± 3.73 |
| NDCG | 0.821 ± 0.178 | 0.821 ± 0.178 | 0.821 ± 0.178 |
| ROUGE-1 | 0.246 ± 0.397 | 0.452 ± 0.521 | 0.291 ± 0.483 |
| ROUGE-2 | 0.194 ± 0.389 | 0.431 ± 0.499 | 0.274 ± 0.483 |
| ROUGE-L | 0.246 ± 0.397 | 0.452 ± 0.521 | 0.291 ± 0.483 |
| Fluency | **0.895 ± 0.031** | 0.821 ± 0.067 | **0.923 ± 0.030** |
| Coherence | 0.198 ± 0.051 | **0.295 ± 0.027** | **0.321 ± 0.019** |
| Relevance | **0.715 ± 0.032** | 0.610 ± 0.073 | **0.729 ± 0.029** |
| Factuality | **0.745 ± 0.071** | 0.629 ± 0.030 | 0.554 ± 0.080 |
| Correctness | **0.645 ± 0.075** | 0.467 ± 0.024 | 0.360 ± 0.051 |
| HHEM | **0.354 ± 0.043** | 0.284 ± 0.019 | 0.236 ± 0.050 |
| Adv. HHEM | **0.047 ± 0.014** | 0.058 ± 0.009 | 0.055 ± 0.009 |

*Note: Bold values indicate best performing metrics. Values are presented as mean ± standard deviation.*

Datasets used: NQ [Kwiatkowski et al., 2019], TriviaQA [Joshi et al., 2017], HotpotQA [Yang et al., 2018], and NarrativeQA [Kociský et al., 2018]

#### Resource Usage Comparison of Different RAG Methods

| Method | CPU Usage (%) | Memory Usage (%) | CPU Power (W) | Energy Total (kWh) | CO2 Emissions (kg) | Carbon Intensity | GPU Util. (%) | GPU Mem. Used (MB) | GPU Mem. Max (MB) | GPU Mem. Total (MB) | GPU Power (W) |
|--------|--------------|-----------------|--------------|-------------------|-------------------|-----------------|--------------|------------------|-----------------|-------------------|--------------|
| **HAH RAG** | **6.73 ± 0.07** | **4.16 ± 0.04** | 4.25 ± 0.04 | **0.0097 ± 0.006** | **0.00068 ± 0.0004** | 70 | **80.96 ± 4.12** | 40408 ± 252 | 40425 | 46068 | **202.83 ± 9.51** |
| **Hybrid RAG** | 6.74 ± 0.01 | 4.19 ± 0.02 | **4.22 ± 0.05** | 0.0290 ± 0.017 | 0.00203 ± 0.001 | 70 | 85.78 ± 2.16 | **40389 ± 239** | **40399** | 46068 | 214.75 ± 5.12 |
| **Naive RAG** | 6.76 ± 0.03 | 4.19 ± 0.01 | 4.29 ± 0.06 | 0.0271 ± 0.013 | 0.00190 ± 0.001 | 70 | 86.31 ± 0.91 | 40399 ± 225 | 40409 | 46068 | 215.99 ± 2.44 |

*Note:*
- **Bold** values indicate best performing metrics. Values are presented as mean ± standard deviation
- Carbon Intensity measured in g CO2/kWh

*Datasets used:* NQ [Kwiatkowski et al., 2019], TriviaQA [Joshi et al., 2017], HotpotQA [Yang et al., 2018], and NarrativeQA [Kociský et al., 2018]
