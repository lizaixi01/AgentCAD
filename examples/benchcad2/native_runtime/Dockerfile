FROM python:3.11.16-slim-trixie

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglx-mesa0 libglvnd0 libgl1-mesa-dri libegl1 libegl-mesa0 \
    libgles2 libgbm1 libx11-6 libx11-xcb1 libxext6 libxrender1 libsm6 libice6 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/native-requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip==26.2.2 \
    && pip install --retries 10 --resume-retries 10 --timeout 120 -r /tmp/native-requirements.txt \
    && rm /tmp/native-requirements.txt
WORKDIR /work
ENV PYTHONPATH=/work PYTHONDONTWRITEBYTECODE=1 XDG_CACHE_HOME=/tmp/.cache \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
CMD ["python"]
