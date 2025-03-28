FROM superlinear/python-gpu:3.11-cuda11.8

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    cmake \
    python3.11-venv \
    libnuma-dev \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN python3.11 -m venv /app/.venv

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip install --upgrade pip

RUN if true; then \
        echo "CUDA detected. Installing GPU requirements..."; \
        pip install -r requirements/requirements_gpu.txt; \
        pip install vllm; \
    else \
        echo "CUDA not detected. Installing CPU requirements..."; \
        pip install -r requirements/requirements_cpu.txt; \
        pip install vllm; \
    fi
RUN pip install "unstructured[all-docs]"

EXPOSE 8509

CMD ["python", "main.py"]