#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

MEMORY_THRESHOLD=7000
RESULTS_DIR="evaluation_results"
LOG_DIR="gpu_benchmarking_logs"
BENCHMARKING_SCRIPT="benchmarking.py"
BENCHMARKING_O1_SCRIPT="benchmarking_o1.py"

debug_mode=false
test_gpus=false
run_all=false
run_all_o1=false
use_o1=false
selected_model=""
pipelines=()

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}


create_directories() {
    mkdir -p "$RESULTS_DIR"
    mkdir -p "$LOG_DIR"
}

# -- get available GPUs
get_available_gpus() {
    local test_gpus="$1"
    local available_gpus=()
    
    # -- check if nvidia-smi is available
    if ! command -v nvidia-smi &> /dev/null; then
        if [ "$test_gpus" = true ]; then
            print_status "Test mode: Simulating multiple GPUs (0 1 3) for testing." >&2
            available_gpus=("0" "1" "3")
        else
            print_warning "nvidia-smi not found. Assuming single GPU (0) for testing." >&2
            available_gpus=("0")
        fi
        echo "${available_gpus[@]}"
        return
    fi
    
    local gpu_info=$(nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null)
    
    if [ -z "$gpu_info" ]; then
        print_warning "Failed to get GPU information. Assuming single GPU (0) for testing." >&2
        available_gpus=("0")
        echo "${available_gpus[@]}"
        return
    fi
    
    while IFS=',' read -r gpu_id memory_used memory_total; do
        gpu_id=$(echo "$gpu_id" | xargs)
        memory_used=$(echo "$memory_used" | xargs)
        memory_total=$(echo "$memory_total" | xargs)

        if [ "$memory_used" -lt "$MEMORY_THRESHOLD" ]; then
            available_gpus+=("$gpu_id")
        fi
    done <<< "$gpu_info"
    
    # -- if no GPUs found, default to GPU 0
    if [ ${#available_gpus[@]} -eq 0 ]; then
        print_warning "No available GPUs found. Defaulting to GPU 0." >&2
        available_gpus=("0")
    fi
    
    IFS=' ' read -ra sorted_gpus <<< "$(printf '%s\n' "${available_gpus[@]}" | sort -n | tr '\n' ' ')"
    available_gpus=("${sorted_gpus[@]}")
    
    echo "${available_gpus[@]}"
}

# -- show GPU status
show_gpu_status() {
    local test_gpus="$1"
    print_status "GPU Status (threshold: ${MEMORY_THRESHOLD}MB):"
    
    if ! command -v nvidia-smi &> /dev/null; then
        if [ "$test_gpus" = true ]; then
            print_status "  GPU 0: Simulated GPU (test mode) - AVAILABLE"
            print_status "  GPU 1: Simulated GPU (test mode) - AVAILABLE"
            print_status "  GPU 3: Simulated GPU (test mode) - AVAILABLE"
        else
            print_status "  GPU 0: Simulated GPU (fallback) - AVAILABLE"
        fi
        return
    fi
    
    local gpu_info=$(nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader,nounits)
    
    while IFS=',' read -r gpu_id gpu_name memory_used memory_total; do
        gpu_id=$(echo "$gpu_id" | xargs)
        gpu_name=$(echo "$gpu_name" | xargs)
        memory_used=$(echo "$memory_used" | xargs)
        memory_total=$(echo "$memory_total" | xargs)
        
        if [ "$memory_used" -lt "$MEMORY_THRESHOLD" ]; then
            print_status "  GPU $gpu_id: $gpu_name (${memory_used}MB/${memory_total}MB used) - AVAILABLE"
        else
            print_warning "  GPU $gpu_id: $gpu_name (${memory_used}MB/${memory_total}MB used) - BUSY"
        fi
    done <<< "$gpu_info"
}

# -- start a single pipeline
start_pipeline() {
    local pipeline="$1"
    local gpu_id="$2"
    local model_name="$3"
    local is_o1="$4"
    
    # -- create model-specific output directory
    local model_dir_name=$(echo "$model_name" | sed 's/[\/:]/_/g' | sed 's/\./_/g')
    local output_dir="${RESULTS_DIR}/${model_dir_name}"
    
    # -- determine script and log file
    local script_name
    local log_suffix
    if [ "$is_o1" = true ]; then
        script_name="$BENCHMARKING_O1_SCRIPT"
        log_suffix="o1"
    else
        script_name="$BENCHMARKING_SCRIPT"
        log_suffix="normal"
    fi
    
    local log_file="$LOG_DIR/gpu${gpu_id}_${pipeline}_${log_suffix}_${model_dir_name}_$(date +%Y%m%d_%H%M%S).log"
    
    print_status "Starting $pipeline pipeline on GPU $gpu_id using model: $model_name" >&2
    print_status "Output directory: $output_dir" >&2
    print_status "Log file: $log_file" >&2
    
    # -- start the pipeline in background
    CUDA_VISIBLE_DEVICES="$gpu_id" python3 "$script_name" --pipeline "$pipeline" --model "$model_name" --output-dir "$output_dir" > "$log_file" 2>&1 &
    
    local pid=$!
    echo "$pid" > "$LOG_DIR/gpu${gpu_id}_${pipeline}_${log_suffix}_${model_dir_name}.pid"
    
    print_success "Started $pipeline pipeline on GPU $gpu_id (PID: $pid)" >&2
    echo $pid
}

# -- run pipelines in parallel
run_parallel_pipelines() {
    local available_gpus=("$@")
    local gpu_count=${#available_gpus[@]}
    local pipeline_count=${#pipelines[@]}
    
    print_status "Running $pipeline_count pipeline(s) on $gpu_count available GPU(s)"
    print_status "Available GPUs: ${available_gpus[*]}"
    print_status "Pipelines: ${pipelines[*]}"
    
    # -- start all pipelines in parallel
    local pids=()
    local gpu_assignments=()
    
    for i in "${!pipelines[@]}"; do
        local pipeline="${pipelines[$i]}"
        local gpu_index=$((i % gpu_count))
        local gpu_id="${available_gpus[$gpu_index]}"
        
        print_status "Starting $pipeline pipeline on GPU $gpu_id"
        
        # -- determine if this is an O1 pipeline
        local is_o1=false
        if [[ "$pipeline" == "Reasoning" || "$pipeline" == "Mini-Reasoning" ]]; then
            is_o1=true
        fi
        
        # -- start the pipeline
        local pid=$(start_pipeline "$pipeline" "$gpu_id" "$selected_model" "$is_o1")
        pids+=($pid)
        gpu_assignments+=("$pipeline → GPU $gpu_id")
        
        print_status "Pipeline $pipeline assigned to GPU $gpu_id (PID: $pid)"
    done
    
    print_status "All pipelines started. PIDs: ${pids[*]}"
    
    # -- wait for all pipelines to complete
    print_status "Waiting for all pipelines to complete..."
    for pid in "${pids[@]}"; do
        if kill -0 $pid 2>/dev/null; then
            print_status "Waiting for PID: $pid"
            wait $pid 2>/dev/null || true
        else
            print_status "PID $pid already completed"
        fi
    done
    
    print_success "All pipelines completed successfully!"
    
    # -- show summary
    print_status "Pipeline execution summary:"
    for assignment in "${gpu_assignments[@]}"; do
        print_status "  $assignment"
    done
}

# -- show help
show_help() {
    echo "GPU Benchmarking Runner Script - Rewritten for True Parallel Execution"
    echo ""
    echo "Usage: $0 [OPTIONS] [PIPELINES...]"
    echo ""
    echo "Options:"
    echo "  -h, --help              Show this help message"
    echo "  -o, --o1               Run O1 reasoning benchmarking instead of normal"
    echo "  -a, --all-pipelines    Run all standard pipelines (Naive, Hybrid, HAH)"
    echo "  -r, --all-o1           Run all O1 reasoning pipelines (Reasoning, Mini-Reasoning)"
    echo "  -m, --model MODEL      Specify model to use for evaluation"
    echo "  -d, --debug            Show detailed GPU information"
    echo "  -t, --test-gpus        Simulate multiple GPUs for testing (0 1 3)"
    echo ""
    echo "Normal Pipelines:"
    echo "  Naive                  Run Naive pipeline"
    echo "  Hybrid                 Run Hybrid pipeline"
    echo "  HAH                    Run HAH pipeline"
    echo ""
    echo "O1 Reasoning Pipelines:"
    echo "  Reasoning              Run full reasoning pipeline"
    echo "  Mini-Reasoning         Run mini-reasoning pipeline"
    echo ""
    echo "Examples:"
    echo "  $0 --all-pipelines                    # Run all standard pipelines in parallel"
    echo "  $0 --all-o1                           # Run all O1 reasoning pipelines in parallel"
    echo "  $0 --model RedHatAI/SmolLM3-3B-quantized.w4a16 --all-pipelines"
    echo "  $0 --test-gpus --debug --all-pipelines  # Test with simulated GPUs"
}

main() {
    local pipelines=()
    local use_o1=false
    local run_all=false
    local run_all_o1=false
    local debug_mode=false
    local test_gpus=false
    local selected_model=""
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            -o|--o1)
                use_o1=true
                shift
                ;;
            -a|--all-pipelines)
                run_all=true
                shift
                ;;
            -r|--all-o1)
                run_all_o1=true
                shift
                ;;
            -m|--model)
                selected_model="$2"
                shift 2
                ;;
            -d|--debug)
                debug_mode=true
                shift
                ;;
            -t|--test-gpus)
                test_gpus=true
                shift
                ;;
            Naive|Hybrid|HAH|Reasoning|Mini-Reasoning)
                pipelines+=("$1")
                shift
                ;;
            *)
                print_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
    
    # -- set default model if not specified
    if [ -z "$selected_model" ]; then
        selected_model="neuralmagic/Meta-Llama-3-8B-Instruct-quantized.w4a16"
    fi
    
    # -- determine pipelines to run
    if [ "$run_all" = true ]; then
        pipelines=("Naive" "Hybrid" "HAH")
        use_o1=false
    elif [ "$run_all_o1" = true ]; then
        pipelines=("Reasoning" "Mini-Reasoning")
        use_o1=true
    elif [ ${#pipelines[@]} -eq 0 ]; then
        print_error "No pipelines specified. Use --all-pipelines, --all-o1, or specify pipeline names."
        show_help
        exit 1
    fi
    
    # -- debug output
    if [ "$debug_mode" = true ]; then
        print_status "Debug: Pipelines to run: ${pipelines[*]}"
        print_status "Debug: run_all: $run_all, run_all_o1: $run_all_o1, use_o1: $use_o1"
        print_status "Debug: Number of pipelines: ${#pipelines[@]}"
        print_status "Debug: Selected model: $selected_model"
    fi
    
    create_directories
    
    local available_gpus=($(get_available_gpus $test_gpus))
    
    if [ "$debug_mode" = true ]; then
        print_status "Debug: Available GPUs: ${available_gpus[*]}"
        print_status "Debug: Number of available GPUs: ${#available_gpus[@]}"
    fi
    
    show_gpu_status $test_gpus
    
    print_success "Found ${#available_gpus[@]} available GPU(s): ${available_gpus[*]}"
    print_status "Using selected model: $selected_model"
    
    run_parallel_pipelines "${available_gpus[@]}"
    
    print_success "All benchmarking tasks completed!"
    print_status "Results saved in: $RESULTS_DIR"
    print_status "Logs saved in: $LOG_DIR"
}

# -- run main function
main "$@"
