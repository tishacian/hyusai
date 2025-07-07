import os
import GPUtil
import subprocess
import logging
from dataclasses import dataclass
from src.globalvariables import (
    GPU_MEMORY_REQUIREMENTS,
    DEFAULT_GPU_MEMORY_REQUIREMENT,
    GPU_MEMORY_SAFETY_MARGIN,
    GPUMemoryStatus,
)


@dataclass
class GPUInfo:
    device_id: int
    name: str
    total_memory_mib: int
    used_memory_mib: int
    free_memory_mib: int
    utilization_percent: int
    temperature_celsius: int
    power_usage_watts: int
    power_capacity_watts: int


class GPUSelector:
    def __init__(self, required_memory_gib: int | None = None):
        """Initialize GPU Selector

        Parameters
        ----------
        required_memory_gib : int | None, optional
            Required GPU memory in GiB. If None,
            uses default.. The default is None.

        Returns
        -------
        None.
        """
        self.required_memory_gib = (
            required_memory_gib or DEFAULT_GPU_MEMORY_REQUIREMENT
        )
        self.logger = logging.getLogger(__name__)
        self._setup_logging()

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )

    def get_gpu_info_nvidia_smi(self) -> list[GPUInfo]:
        """GPU information using nvidia-smi command.

        Returns
        -------
        list[GPUInfo]
            List of GPUInfo objects for each detected GPU.
        """
        try:
            query = (
                "--query-gpu=index,name,memory.total,memory.used,"
                "memory.free,utilization.gpu,temperature.gpu,"
                "power.draw,power.limit"
            )
            result = subprocess.run(
                ["nvidia-smi", query, "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                check=True,
            )

            gpu_info_list = []
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    parts = [part.strip() for part in line.split(",")]
                    if len(parts) >= 9:

                        def parse_mem(val):
                            try:
                                return float(val)
                            except Exception:
                                return 0.0

                        total_mem = parse_mem(parts[2])
                        used_mem = parse_mem(parts[3])
                        free_mem = parse_mem(parts[4])
                        #  -- if the value is less than 200, assume it's GiB, convert to MiB
                        if total_mem < 200:
                            total_mem *= 1024
                            used_mem *= 1024
                            free_mem *= 1024

                        total_mem = int(total_mem)
                        used_mem = int(used_mem)
                        free_mem = int(free_mem)
                        try:
                            utilization = int(float(parts[5]))
                        except Exception:
                            utilization = 0
                        try:
                            temp = int(float(parts[6]))
                        except Exception:
                            temp = 0
                        try:
                            power_usage = (
                                int(float(parts[7]))
                                if parts[7] != "N/A"
                                else 0
                            )
                        except Exception:
                            power_usage = 0
                        try:
                            power_capacity = (
                                int(float(parts[8]))
                                if parts[8] != "N/A"
                                else 0
                            )
                        except Exception:
                            power_capacity = 0
                        # -- GPUInfo
                        gpu_info = GPUInfo(
                            device_id=int(parts[0]),
                            name=parts[1],
                            total_memory_mib=total_mem,
                            used_memory_mib=used_mem,
                            free_memory_mib=free_mem,
                            utilization_percent=utilization,
                            temperature_celsius=temp,
                            power_usage_watts=power_usage,
                            power_capacity_watts=power_capacity,
                        )
                        gpu_info_list.append(gpu_info)

            return gpu_info_list

        except (
            subprocess.CalledProcessError,
            FileNotFoundError,
            ValueError,
        ) as e:
            self.logger.warning("Failed to get GPU info via nvidia-smi: %s", e)
            return []

    def get_gpu_info_gputil(self) -> list[GPUInfo]:
        """
        Get GPU information using GPUtil.

        Returns
        -------
        list[GPUInfo]
            List of GPUInfo objects for each detected GPU.
        """
        gpu_info_list = []
        try:
            gpus = GPUtil.getGPUs()
            for gpu in gpus:
                gpu_info = GPUInfo(
                    device_id=gpu.id,
                    name=gpu.name,
                    total_memory_mib=int(gpu.memoryTotal),
                    used_memory_mib=int(gpu.memoryUsed),
                    free_memory_mib=int(gpu.memoryFree),
                    utilization_percent=int(gpu.load * 100),
                    temperature_celsius=(
                        int(gpu.temperature)
                        if gpu.temperature is not None
                        else 0
                    ),
                    power_usage_watts=(
                        int(gpu.powerUsage)
                        if hasattr(gpu, "powerUsage")
                        and gpu.powerUsage is not None
                        else 0
                    ),
                    power_capacity_watts=0,
                )
                gpu_info_list.append(gpu_info)
        except Exception as e:
            self.logger.warning("Failed to get GPU info via GPUtil: %s", e)
        return gpu_info_list

    def get_gpu_info(self) -> list[GPUInfo]:
        """GPU information using the best available method (GPUtil preferred).

        Returns
        -------
        list[GPUInfo]
            List of GPUInfo objects for each detected GPU.
        """
        gpu_info = self.get_gpu_info_gputil()
        if not gpu_info:
            # -- use nvidia-smi instead
            gpu_info = self.get_gpu_info_nvidia_smi()
        return gpu_info

    def evaluate_gpu_suitability(
        self, gpu_info: GPUInfo
    ) -> tuple[GPUMemoryStatus, float]:
        """Evaluate if a GPU is suitable for the required memory.

        Parameters
        ----------
        gpu_info : GPUInfo
            GPU information object.

        Returns
        -------
        tuple[GPUMemoryStatus, float]
            Status and available memory in GiB.
        """
        # --convert MiB to GiB
        free_memory_gib = gpu_info.free_memory_mib / 1024  # GiB conversion
        available_memory_gib = free_memory_gib - GPU_MEMORY_SAFETY_MARGIN
        if available_memory_gib >= self.required_memory_gib:
            return GPUMemoryStatus.AVAILABLE, available_memory_gib
        elif free_memory_gib > 0:
            return GPUMemoryStatus.INSUFFICIENT, available_memory_gib
        else:
            return GPUMemoryStatus.UNAVAILABLE, 0.0

    def select_best_gpu(self) -> int | None:
        """Select the available GPU based on memory requirements, 
        w/ priority from last index.

        Returns
        -------
        int | None
            Device ID of the best GPU, or None if no suitable GPU found.
        """
        gpu_info_list = self.get_gpu_info()
        if not gpu_info_list:
            self.logger.warning("No GPUs found")
            return None
        self.logger.info(f"Found {len(gpu_info_list)} GPU(s)")
        # eval each GPU
        suitable_gpus = []
        for gpu_info in gpu_info_list:
            status, available_memory = self.evaluate_gpu_suitability(gpu_info)
            self.logger.info(
                f"GPU {gpu_info.device_id} ({gpu_info.name}): "
                f"Total: {gpu_info.total_memory_mib/1024:.1f} GiB, "
                f"Free: {gpu_info.free_memory_mib/1024:.1f} GiB, "
                f"Status: {status.value}"
            )
            if status == GPUMemoryStatus.AVAILABLE:
                suitable_gpus.append((gpu_info.device_id, available_memory))
        
        if not suitable_gpus:
            self.logger.error(
                f"No GPU with sufficient memory found. "
                f"Required: {self.required_memory_gib} GiB"
            )
            return None
        
        # -- reverse sort by device_id in descending order then select available GPU w/ most mem
        suitable_gpus.sort(key=lambda x: x[0], reverse=True)
        best_gpu_id = None
        best_available_memory = 0
        
        for device_id, available_memory in suitable_gpus:
            if best_gpu_id is None or available_memory > best_available_memory:
                best_gpu_id = device_id
                best_available_memory = available_memory
        
        self.logger.info(
            f"Selected GPU {best_gpu_id} (last index priority) for use"
        )
        return best_gpu_id

    def set_cuda_visible_devices(self, device_id: int) -> None:
        """Set CUDA_VISIBLE_DEVICES environment variable.

        Parameters
        ----------
        device_id : int
            GPU device ID to make visible.
        """
        os.environ["CUDA_VISIBLE_DEVICES"] = str(device_id)
        self.logger.info(f"Set CUDA_VISIBLE_DEVICES to {device_id}")

    def get_memory_requirement_for_model(self, model_name: str) -> int:
        """Memory requirement based on specific model.

        Parameters
        ----------
        model_name : str
            Name of the model.

        Returns
        -------
        int
            Required memory in GiB.
        """
        return GPU_MEMORY_REQUIREMENTS.get(
            model_name, DEFAULT_GPU_MEMORY_REQUIREMENT
        )

    def auto_select_gpu(self, model_name: str | None = None) -> int | None:
        """Automatically select the GPU for the given model.

        Parameters
        ----------
        model_name : str, optional
            Model name to determine memory requirements.

        Returns
        -------
        int | None
            Selected GPU device ID, or None if no suitable GPU found.
        """
        if model_name:
            self.required_memory_gib = self.get_memory_requirement_for_model(
                model_name
            )
            self.logger.info(
                f"Model {model_name} requires {self.required_memory_gib} GiB"
            )
        selected_gpu = self.select_best_gpu()
        if selected_gpu is not None:
            self.set_cuda_visible_devices(selected_gpu)
        return selected_gpu
