FROM superlinear/python-gpu:3.11-cuda11.8

WORKDIR /app

ARG LANGS="eng fra deu spa ita por kor ara"

RUN apt-get update \
    && apt-get install -y \
        cmake \
        g++ \
        gcc \
        libnuma-dev \
        make \
        python3.11-venv \
        tesseract-ocr \
    && for lang in $LANGS; do \
        apt-get install -y tesseract-ocr-"$lang"; \
    done \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN python3.11 -m venv /app/.venv

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"


RUN pip install --upgrade pip \
    && pip install -r requirements/requirements.txt \
    && if [ -n "$CUDA_VERSION" ] || command -v nvidia-smi &> /dev/null; then \
        echo "GPU detected in Docker environment"; \
        pip install vllm psutil; \
        echo "GPU=1" > .device_config; \
    else \
        echo "No GPU detected in Docker environment"; \
        pip install llama_cpp_python huggingface-hub; \
        echo "GPU=0" > .device_config; \
    fi \
    && pip install "unstructured[all-docs]" \
    && pip install tesserocr \
    && pip install pytesseract

ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/4.00/tessdata

EXPOSE 8509

CMD ["python", "main.py"]