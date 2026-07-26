FROM python:3.12-slim

WORKDIR /app

COPY apps/api /app

RUN pip install --no-cache-dir .

COPY infrastructure/docker/container-entrypoint.py /container-entrypoint.py

ENTRYPOINT ["python", "/container-entrypoint.py"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
