# GPU Benchmarking Scripts

This directory contains scripts to automatically run benchmarking on available GPUs.

## Available Scripts

### 1. `run_benchmarking_gpu.sh` - Full-Featured GPU Runner
The main script with comprehensive features for running benchmarking on multiple GPUs.

**Features:**
- Automatic GPU availability detection
- Process management and monitoring
- Log file management
- Cleanup utilities
- Support for both normal and O1 benchmarking

**Usage:**
```bash
# Run all pipelines on available GPUs
./run_benchmarking_gpu.sh --all-pipelines

# Run O1 benchmarking on all pipelines
./run_benchmarking_gpu.sh --o1 --all-pipelines

# Run specific pipelines
./run_benchmarking_gpu.sh Naive HAH

# Run O1 with specific pipeline
./run_benchmarking_gpu.sh --o1 HAH

# Check running processes
./run_benchmarking_gpu.sh --status

# Stop all processes
./run_benchmarking_gpu.sh --kill

# Cleanup old files
./run_benchmarking_gpu.sh --cleanup

# Show help
./run_benchmarking_gpu.sh --help
```

### 2. `quick_benchmark.sh` - Simple Quick Start
A simplified script for quick benchmarking setup.

**Usage:**
```bash
# Run all pipelines on available GPUs
./quick_benchmark.sh
```

### 3. `monitor_gpu.sh` - GPU Monitoring
Monitor GPU usage and running processes.

**Usage:**
```bash
# Continuous monitoring (refreshes every 5 seconds)
./monitor_gpu.sh

# Single check
./monitor_gpu.sh check

# Show help
./monitor_gpu.sh help
```

## GPU Detection Logic

The scripts automatically detect available GPUs based on memory usage:

- **Available**: Memory usage < 1000MB (4MB baseline + small overhead)
- **Busy**: Memory usage ≥ 1000MB

## Example Workflow

### 1. Check GPU Status
```bash
./monitor_gpu.sh check
```

### 2. Run All Pipelines
```bash
# Normal benchmarking
./run_benchmarking_gpu.sh --all-pipelines

# O1 benchmarking
./run_benchmarking_gpu.sh --o1 --all-pipelines
```

### 3. Monitor Progress
```bash
# In another terminal
./monitor_gpu.sh

# Or check logs
tail -f gpu*_*.log
```

### 4. Check Results
```bash
ls -la evaluation_results/
```

## Output Structure

### Log Files
- **Location**: `gpu_benchmarking_logs/` or current directory
- **Format**: `gpu{ID}_{pipeline}_{type}_{timestamp}.log`
- **Example**: `gpu1_Naive_normal_20240916_140530.log`

### Results
- **Location**: `evaluation_results/`
- **Files**: 
  - `{pipeline}_evaluation_summary.csv`
  - `{dataset}/{pipeline}_metrics_over_time.csv`
  - `{dataset}/{pipeline}_resource_metrics.csv`

## Process Management

### Check Running Processes
```bash
./run_benchmarking_gpu.sh --status
```

### Stop All Processes
```bash
./run_benchmarking_gpu.sh --kill
```

### Cleanup
```bash
./run_benchmarking_gpu.sh --cleanup
```

## Troubleshooting

### No Available GPUs
If all GPUs are busy:
```bash
# Check what's running
nvidia-smi

# Wait and try again
./monitor_gpu.sh check
```

### Process Stuck
```bash
# Kill all benchmarking processes
./run_benchmarking_gpu.sh --kill

# Check for zombie processes
ps aux | grep python
```

### Permission Issues
```bash
# Make scripts executable
chmod +x *.sh
```

### Virtual Environment
Make sure you're in the correct virtual environment:
```bash
# Activate virtual environment
source .venv/bin/activate

# Or run install script
./install.sh
```

## Advanced Usage

### Custom Memory Threshold
Edit the scripts to change the memory threshold:
```bash
# In run_benchmarking_gpu.sh, change:
MEMORY_THRESHOLD=1000  # MB

# In quick_benchmark.sh, change:
if [ "$memory_used" -lt 1000 ]; then
```

### Run Specific Datasets
Modify the dataset configuration in `dataset_manager.py` to run specific datasets only.

### Custom GPU Selection
Manually set `CUDA_VISIBLE_DEVICES`:
```bash
CUDA_VISIBLE_DEVICES=1,2 python3 benchmarking.py --pipeline HAH
```

## Running Pipelines with Different Models

### Available Pipelines

**Normal Pipelines:**
- `Naive` - Basic RAG pipeline
- `Hybrid` - Hybrid retrieval pipeline
- `HAH` - Hyper-layered Asynchronous Hybrid RAG

**O1 Reasoning Pipelines:**
- `Reasoning` - Full reasoning pipeline
- `Mini-Reasoning` - Mini reasoning pipeline

### Available Models

Common models you can use:
- `neuralmagic/Meta-Llama-3-8B-Instruct-quantized.w4a16` (default)
- `suayptalha/DeepSeek-R1-Distill-Llama-3B`
- `RedHatAI/DeepSeek-R1-Distill-Llama-8B-quantized.w4a16`
- `RedHatAI/SmolLM3-3B-quantized_w4a16`
- `RedHatAI/gemma-2-9b-it-quantized_w4a16`
- `RedHatAI/gemma-3-4b-it-quantized_w4a16`
- `microsoft/Phi-3-mini-4k-instruct`

### Using GPU Script (Recommended)

#### Run All Normal Pipelines with a Specific Model
```bash
# Run Naive, Hybrid, and HAH pipelines with a specific model
./run_benchmarking_gpu.sh --model "suayptalha/DeepSeek-R1-Distill-Llama-3B" --all-pipelines

# Run with Gemma-3-4B model
./run_benchmarking_gpu.sh --model "RedHatAI/gemma-3-4b-it-quantized_w4a16" --all-pipelines

# Run with Phi-3-mini model
./run_benchmarking_gpu.sh --model "microsoft/Phi-3-mini-4k-instruct" --all-pipelines
```

#### Run Specific Pipelines with a Model
```bash
# Run only HAH pipeline with DeepSeek model
./run_benchmarking_gpu.sh --model "suayptalha/DeepSeek-R1-Distill-Llama-3B" HAH

# Run multiple specific pipelines
./run_benchmarking_gpu.sh --model "RedHatAI/gemma-2-9b-it-quantized_w4a16" Naive Hybrid HAH

# Run O1 reasoning pipelines with a model
./run_benchmarking_gpu.sh --model "neuralmagic/Meta-Llama-3-8B-Instruct-quantized.w4a16" --all-o1
```

#### Run O1 Reasoning Pipelines
```bash
# Run all O1 reasoning pipelines (Reasoning, Mini-Reasoning) with default model
./run_benchmarking_gpu.sh --all-o1

# Run O1 reasoning pipelines with specific model
./run_benchmarking_gpu.sh --model "suayptalha/DeepSeek-R1-Distill-Llama-3B" --all-o1

# Run specific O1 pipeline
./run_benchmarking_gpu.sh --model "RedHatAI/SmolLM3-3B-quantized_w4a16" Reasoning
```

### Using Python Scripts Directly

#### Basic Syntax
```bash
python3 benchmarking.py --pipeline <PIPELINE> --model <MODEL_NAME> [--output-dir <DIR>] [--country-code <CODE>]
```

#### Examples

**Run Naive pipeline with DeepSeek model:**
```bash
python3 benchmarking.py --pipeline Naive --model "suayptalha/DeepSeek-R1-Distill-Llama-3B"
```

**Run HAH pipeline with Gemma-3-4B model:**
```bash
python3 benchmarking.py --pipeline HAH --model "RedHatAI/gemma-3-4b-it-quantized_w4a16" --output-dir evaluation_results/gemma_3_4b
```

**Run Hybrid pipeline with Phi-3-mini model:**
```bash
python3 benchmarking.py --pipeline Hybrid --model "microsoft/Phi-3-mini-4k-instruct" --country-code US
```

**Run O1 Reasoning pipeline:**
```bash
python3 benchmarking_o1.py --pipeline Reasoning --model "neuralmagic/Meta-Llama-3-8B-Instruct-quantized.w4a16"
```

**Run Mini-Reasoning pipeline:**
```bash
python3 benchmarking_o1.py --pipeline Mini-Reasoning --model "RedHatAI/SmolLM3-3B-quantized_w4a16"
```

### Using Specific GPU

**Set GPU manually:**
```bash
# Run on GPU 1
CUDA_VISIBLE_DEVICES=1 python3 benchmarking.py --pipeline HAH --model "suayptalha/DeepSeek-R1-Distill-Llama-3B"

# Run on GPU 2
CUDA_VISIBLE_DEVICES=2 python3 benchmarking.py --pipeline Naive --model "RedHatAI/gemma-2-9b-it-quantized_w4a16"

# Run on multiple GPUs (for parallel execution)
CUDA_VISIBLE_DEVICES=1,2 python3 benchmarking.py --pipeline Hybrid --model "neuralmagic/Meta-Llama-3-8B-Instruct-quantized.w4a16"
```

### Complete Examples

**Example 1: Benchmark all pipelines with DeepSeek model**
```bash
./run_benchmarking_gpu.sh --model "suayptalha/DeepSeek-R1-Distill-Llama-3B" --all-pipelines
```

**Example 2: Compare HAH pipeline across different models**
```bash
# Run HAH with DeepSeek
./run_benchmarking_gpu.sh --model "suayptalha/DeepSeek-R1-Distill-Llama-3B" HAH

# Run HAH with Gemma-3-4B
./run_benchmarking_gpu.sh --model "RedHatAI/gemma-3-4b-it-quantized_w4a16" HAH

# Run HAH with Llama-3-8B
./run_benchmarking_gpu.sh --model "neuralmagic/Meta-Llama-3-8B-Instruct-quantized.w4a16" HAH
```

**Example 3: Run specific pipeline-model combinations**
```bash
# Naive with SmolLM
python3 benchmarking.py --pipeline Naive --model "RedHatAI/SmolLM3-3B-quantized_w4a16"

# Hybrid with Gemma-2-9B
python3 benchmarking.py --pipeline Hybrid --model "RedHatAI/gemma-2-9b-it-quantized_w4a16"

# HAH with Phi-3-mini
python3 benchmarking.py --pipeline HAH --model "microsoft/Phi-3-mini-4k-instruct"
```

### Output Locations

Results are saved in model-specific directories:
- Default: `evaluation_results/{model_name}/{pipeline}_evaluation_summary.csv`
- Custom: `{output_dir}/{model_name}/{pipeline}_evaluation_summary.csv`

Example paths:
- `evaluation_results/suayptalha_DeepSeek-R1-Distill-Llama-3B/HAH_evaluation_summary.csv`
- `evaluation_results/RedHatAI_gemma-3-4b-it-quantized_w4a16/Naive_evaluation_summary.csv`

## Performance Tips

1. **Start with one pipeline** to test the setup
2. **Monitor GPU memory** to avoid OOM errors
3. **Use different GPUs** for different pipelines to parallelize
4. **Check logs regularly** to catch errors early
5. **Clean up old results** to save disk space
6. **Use quantized models** for lower memory usage (e.g., `w4a16` quantized models)

## Example Commands for Setup

```bash
# Quick start - run all pipelines
./quick_benchmark.sh

# Full monitoring
./monitor_gpu.sh

# Run O1 benchmarking
./run_benchmarking_gpu.sh --o1 --all-pipelines

# Check status
./run_benchmarking_gpu.sh --status

# Stop everything
./run_benchmarking_gpu.sh --kill
```

This should efficiently use any available GPUs (in our case 1, 2, 3) while GPU 0 is busy with other tasks.
