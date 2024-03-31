from dataclasses import dataclass


@dataclass
class ComputeCosts:
    """Constants for compute costs in euros"""

    CPU_COST_PER_HOUR: float = 0.05  # €/hour
    GPU_COST_PER_HOUR: float = 0.95  # €/hour
    MEMORY_COST_PER_GB_HOUR: float = 0.01  # €/GB-hour
    POWER_COST_PER_KWH: float = 0.15  # €/kWh


class ResourceCost:
    def __init__(self, sampling_interval: float = 0.1):
        """Initialize cost calculator

        Args:
            sampling_interval: Time interval between resource measurements in seconds
        """
        self.sampling_interval = sampling_interval
        self.costs = ComputeCosts()

    def calculate_costs(self, resource_metrics: dict) -> dict[str, float]:
        """Calculate costs from resource metrics

        Args:
            resource_metrics: Dictionary containing resource usage metrics

        Returns:
            Dictionary with calculated costs in euros
        """
        hours = self.sampling_interval / 3600  # Convert sampling interval to hours
        cpu_cost = (
            resource_metrics.get("cpu_percent_avg", 0)
            / 100
            * self.costs.CPU_COST_PER_HOUR
            * hours
        )
        gpu_cost = 0
        if "gpu_utilization_avg" in resource_metrics:
            gpu_cost = (
                resource_metrics["gpu_utilization_avg"]
                / 100
                * self.costs.GPU_COST_PER_HOUR
                * hours
            )

        memory_gb = (
            resource_metrics.get("memory_percent_avg", 0)
            / 100
            * resource_metrics.get("total_memory_gb", 16)
        )
        memory_cost = memory_gb * self.costs.MEMORY_COST_PER_GB_HOUR * hours
        total_energy_kwh = resource_metrics.get("total_energy_consumed", 0)
        power_cost = total_energy_kwh * self.costs.POWER_COST_PER_KWH
        total_cost = cpu_cost + gpu_cost + memory_cost + power_cost

        return {
            "compute_cost_cpu": cpu_cost,
            "compute_cost_gpu": gpu_cost,
            "memory_cost": memory_cost,
            "power_cost": power_cost,
            "total_cost": total_cost,
        }

    def calculate_cost_per_query(self, total_cost: float, num_queries: int) -> float:
        """Calculate cost per query

        Args:
            total_cost: Total cost in euros
            num_queries: Number of queries processed

        Returns:
            Cost per query in euros
        """
        return total_cost / max(num_queries, 1)
