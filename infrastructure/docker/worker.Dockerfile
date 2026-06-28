FROM python:3.12-slim

WORKDIR /srv

COPY apps/api /srv/api
RUN pip install --no-cache-dir /srv/api

COPY apps/worker /srv/worker
RUN pip install --no-cache-dir /srv/worker

CMD ["python", "-m", "celery", "-A", "app.celery_app:celery_app", "worker", "--loglevel=info", "--queues=verification.quick,verification.standard,verification.deep"]
