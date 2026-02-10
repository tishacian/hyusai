FROM superlinear/python-gpu:3.11-cuda11.8

WORKDIR /app

ARG LANGS="eng fra deu spa ita por kor ara"
ARG DEVICE="gpu"

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
    && if [ "$DEVICE" = "gpu" ]; then \
        echo "Installing GPU requirements..."; \
        pip install -r requirements/shared.txt -r requirements/gpu.txt -r requirements/standalone_interface.txt; \
    else \
        echo "Installing CPU requirements..."; \
        pip install -r requirements/shared.txt -r requirements/cpu.txt -r requirements/standalone_interface.txt; \
    fi

ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/4.00/tessdata

EXPOSE 8509

CMD ["python", "main.py"]
