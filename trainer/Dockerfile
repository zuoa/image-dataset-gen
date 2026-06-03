FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRAINER_WORK_ROOT=/app/work \
    TRAINER_MODEL_DIR=/app/models \
    TRAINER_YOLO_WORKERS=0 \
    TRAINER_NOFILE_LIMIT=65535 \
    YOLO_CONFIG_DIR=/app/models/.ultralytics

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/work /app/models /app/models/.ultralytics

EXPOSE 8010

CMD ["python", "-m", "app.worker"]
