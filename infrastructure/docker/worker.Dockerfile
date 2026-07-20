FROM python:3.12-slim

WORKDIR /srv

COPY apps/api /srv/api
RUN pip install --no-cache-dir /srv/api

COPY apps/worker /srv/worker
RUN pip install --no-cache-dir /srv/worker
RUN python -m playwright install --with-deps chromium

COPY infrastructure/docker/container-entrypoint.py /container-entrypoint.py

ENTRYPOINT ["python", "/container-entrypoint.py"]

CMD ["python", "-m", "celery", "-A", "app.celery_app:celery_app", "worker", "--loglevel=info", "--queues=verification.quick,verification.standard,verification.deep"]
