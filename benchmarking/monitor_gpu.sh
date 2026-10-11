#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_header() {
    echo -e "${BLUE}================================${NC}"
    echo -e "${BLUE}  GPU Benchmarking Monitor${NC}"
    echo -e "${BLUE}================================${NC}"
}

print_gpu_status() {
    echo -e "\n${YELLOW}GPU Status:${NC}"
    nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader,nounits | while IFS=',' read -r gpu_id name memory_used memory_total gpu_util temp; do
        gpu_id=$(echo "$gpu_id" | xargs)
        name=$(echo "$name" | xargs)
        memory_used=$(echo "$memory_used" | xargs)
        memory_total=$(echo "$memory_total" | xargs)
        gpu_util=$(echo "$gpu_util" | xargs)
        temp=$(echo "$temp" | xargs)
        memory_percent=$((memory_used * 100 / memory_total))
        if [ "$memory_used" -lt 1000 ]; then
            status="${GREEN}AVAILABLE${NC}"
        elif [ "$memory_percent" -lt 50 ]; then
            status="${YELLOW}MODERATE${NC}"
        else
            status="${RED}BUSY${NC}"
        fi
        
        echo -e "  GPU $gpu_id: $name - ${memory_used}MB/${memory_total}MB (${memory_percent}%) - ${gpu_util}% util - ${temp}°C - $status"
    done
}

print_running_processes() {
    echo -e "\n${YELLOW}Running Benchmarking Processes:${NC}"
    
    local found_processes=false
    
    ps aux | grep -E "(benchmarking\.py|benchmarking-o1\.py)" | grep -v grep | while read -r line; do
        if [ -n "$line" ]; then
            found_processes=true
            echo "  $line"
        fi
    done
    
    if [ "$found_processes" = false ]; then
        echo -e "  ${YELLOW}No benchmarking processes found${NC}"
    fi
}

print_log_files() {
    echo -e "\n${YELLOW}Recent Log Files:${NC}"
    
    if [ -d "gpu_benchmarking_logs" ]; then
        ls -la gpu_benchmarking_logs/*.log 2>/dev/null | tail -5 | while read -r line; do
            echo "  $line"
        done
    else
        echo -e "  ${YELLOW}No log directory found${NC}"
    fi
    
    ls -la gpu*_*.log 2>/dev/null | tail -5 | while read -r line; do
        echo "  $line"
    done
}

print_results() {
    echo -e "\n${YELLOW}Results Directory:${NC}"
    
    if [ -d "evaluation_results" ]; then
        echo "  Results found in evaluation_results/:"
        ls -la evaluation_results/ | grep -E "(\.csv|\.log)" | while read -r line; do
            echo "    $line"
        done
    else
        echo -e "  ${YELLOW}No results directory found${NC}"
    fi
}

print_usage() {
    echo -e "\n${YELLOW}Usage Commands:${NC}"
    echo "  ./run_benchmarking_gpu.sh --all-pipelines    # Run all pipelines"
    echo "  ./run_benchmarking_gpu.sh --o1 --all-pipelines # Run O1 pipelines"
    echo "  ./quick_benchmark.sh                         # Quick start"
    echo "  ./run_benchmarking_gpu.sh --status           # Show process status"
    echo "  ./run_benchmarking_gpu.sh --kill             # Stop all processes"
}

monitor() {
    while true; do
        clear
        print_header
        print_gpu_status
        print_running_processes
        print_log_files
        print_results
        print_usage
        
        echo -e "\n${BLUE}Press Ctrl+C to exit monitoring${NC}"
        sleep 5
    done
}

single_check() {
    print_header
    print_gpu_status
    print_running_processes
    print_log_files
    print_results
}

case "${1:-monitor}" in
    "monitor"|"-m")
        monitor
        ;;
    "check"|"-c")
        single_check
        ;;
    "help"|"-h")
        echo "GPU Monitoring Script"
        echo ""
        echo "Usage: $0 [OPTION]"
        echo ""
        echo "Options:"
        echo "  monitor, -m    Continuous monitoring (default)"
        echo "  check, -c      Single check"
        echo "  help, -h       Show this help"
        ;;
    *)
        echo "Unknown option: $1"
        echo "Use '$0 help' for usage information"
        exit 1
        ;;
esac
