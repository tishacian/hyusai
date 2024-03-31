#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Dec  6 01:40:22 2024

@author: kennethezukwoke
"""

import threading
import GPUtil
import torch
import psutil
from typing import Dict, List, Optional
import numpy as np
from time import time, sleep
from dataclasses import dataclass
from codecarbon import EmissionsTracker


@dataclass
class GPUMetrics:
    gpu_utilization: float
    gpu_memory_used: float
    gpu_memory_total: float
    power_usage: float  # in watts
    timestamp: float


@dataclass
class CPUMetrics:
    cpu_percent: float
    memory_percent: float
    power_usage: float  # in watts
    timestamp: float


@dataclass
class EmissionMetrics:
    energy_consumed: float  # in kWh
    co2_emissions: float  # in kg
    timestamp: float


class ResourceMonitor:
    def __init__(self, sampling_interval: float = 0.1, country_code: str = "FR"):
        """Initialize the resource monitor"""
        self.sampling_interval = sampling_interval
        self.country_code = country_code
        self.is_monitoring = False
        self.gpu_metrics: List[GPUMetrics] = []
        self.cpu_metrics: List[CPUMetrics] = []
        self.emission_metrics: List[EmissionMetrics] = []
        self._monitor_thread: Optional[threading.Thread] = None
        self.cpu = psutil.cpu_times_percent()
        self.cpu_power_start = self._get_cpu_power()

        try:
            self.emissions_tracker = EmissionsTracker(
                project_name="rag_evaluation",
                output_dir="emission_logs",
                log_level="warning",
                measure_power_secs=self.sampling_interval,
                save_to_file=False,
            )
        except Exception as e:
            print(f"Warning: Could not initialize emissions tracker: {e}")
            self.emissions_tracker = None

        self.carbon_intensity = self._get_carbon_intensity(country_code)

    def _get_cpu_power(self) -> float:
        """Get CPU power consumption estimate"""
        try:
            freq = psutil.cpu_freq()
            if freq is None:
                return 65.0  # default TDP for a typical CPU

            base_power = 65.0
            freq_ratio = freq.current / freq.max if freq.max > 0 else 1.0
            cpu_percent = psutil.cpu_percent() / 100.0

            return base_power * freq_ratio * cpu_percent
        except Exception as e:
            print(f"Warning: Could not get CPU power: {e}")
            return 65.0

    def _get_gpu_power(self) -> float:
        """Get GPU power consumption"""
        try:
            if torch.cuda.is_available():
                gpu = GPUtil.getGPUs()[0]
                if hasattr(gpu, "powerUsage") and gpu.powerUsage is not None:
                    return float(gpu.powerUsage)
                else:
                    return float(gpu.load * 250)
            return 0.0
        except Exception as e:
            print(f"Warning: Could not get GPU power: {e}")
            return 0.0

    def _get_carbon_intensity(self, country_code: str) -> float:
        """Get carbon intensity for a given country"""
        carbon_intensities = {
            "US": 385,
            "CN": 555,
            "IN": 725,
            "GB": 225,
            "DE": 350,
            "FR": 70,
            "JP": 460,
        }
        return carbon_intensities.get(country_code, 475)

    def _collect_metrics(self):
        """Collect metrics continuously"""
        cumulative_energy = 0.0

        while self.is_monitoring:
            try:
                current_time = time()
                # -- CPU metrics
                cpu_percent = psutil.cpu_percent(interval=None)
                memory = psutil.virtual_memory()
                cpu_power = self._get_cpu_power()

                self.cpu_metrics.append(
                    CPUMetrics(
                        cpu_percent=cpu_percent,
                        memory_percent=memory.percent,
                        power_usage=cpu_power,
                        timestamp=current_time,
                    )
                )

                # -- GPU metrics if available
                gpu_power = 0.0
                if torch.cuda.is_available():
                    gpu = GPUtil.getGPUs()[0]
                    gpu_power = self._get_gpu_power()

                    self.gpu_metrics.append(
                        GPUMetrics(
                            gpu_utilization=gpu.load * 100,
                            gpu_memory_used=gpu.memoryUsed,
                            gpu_memory_total=gpu.memoryTotal,
                            power_usage=gpu_power,
                            timestamp=current_time,
                        )
                    )

                # Calculate energy and emissions
                total_power = cpu_power + gpu_power
                energy_kwh = (total_power * self.sampling_interval) / (1000 * 3600)
                cumulative_energy += energy_kwh
                emissions_kg = (energy_kwh * self.carbon_intensity) / 1000

                self.emission_metrics.append(
                    EmissionMetrics(
                        energy_consumed=energy_kwh,
                        co2_emissions=emissions_kg,
                        timestamp=current_time,
                    )
                )

                sleep(self.sampling_interval)

            except Exception as e:
                print(f"Error collecting metrics: {e}")
                sleep(self.sampling_interval)

    def start_monitoring(self):
        """Start collecting metrics"""
        self.is_monitoring = True
        self.gpu_metrics = []
        self.cpu_metrics = []
        self.emission_metrics = []
        if self.emissions_tracker:
            try:
                self.emissions_tracker.start()
            except Exception as e:
                print(f"Warning: Could not start emissions tracker: {e}")

        self._monitor_thread = threading.Thread(target=self._collect_metrics)
        self._monitor_thread.daemon = True
        self._monitor_thread.start()

    def stop_monitoring(self) -> Dict[str, float]:
        """Stop collecting metrics and return summary"""
        self.is_monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)  # 2 seconds for thread to finish

        emissions = 0.0
        if self.emissions_tracker:
            try:
                emissions = self.emissions_tracker.stop()
            except Exception as e:
                print(f"Warning: Could not get emissions from tracker: {e}")

        # -- Calculate metrics
        metrics_summary = {
            "cpu_percent_avg": (
                np.mean([m.cpu_percent for m in self.cpu_metrics])
                if self.cpu_metrics
                else 0.0
            ),
            "memory_percent_avg": (
                np.mean([m.memory_percent for m in self.cpu_metrics])
                if self.cpu_metrics
                else 0.0
            ),
            "cpu_power_avg": (
                np.mean([m.power_usage for m in self.cpu_metrics])
                if self.cpu_metrics
                else 0.0
            ),
            "total_energy_consumed": (
                sum(m.energy_consumed for m in self.emission_metrics)
                if self.emission_metrics
                else 0.0
            ),
            "total_co2_emissions": (
                sum(m.co2_emissions for m in self.emission_metrics)
                if self.emission_metrics
                else 0.0
            ),
            "carbon_intensity": self.carbon_intensity,
            "emissions_tracked": emissions,
        }

        # -- Add GPU metrics if available
        if self.gpu_metrics:
            metrics_summary.update(
                {
                    "gpu_utilization_avg": np.mean(
                        [m.gpu_utilization for m in self.gpu_metrics]
                    ),
                    "gpu_memory_used_avg": np.mean(
                        [m.gpu_memory_used for m in self.gpu_metrics]
                    ),
                    "gpu_memory_used_max": max(
                        m.gpu_memory_used for m in self.gpu_metrics
                    ),
                    "gpu_memory_total": self.gpu_metrics[0].gpu_memory_total,
                    "gpu_power_avg": np.mean([m.power_usage for m in self.gpu_metrics]),
                }
            )

        return metrics_summary
