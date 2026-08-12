FROM python:3.12-slim

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /srv

COPY apps/api /srv/api
RUN pip install --no-cache-dir /srv/api

COPY apps/worker /srv/worker
RUN pip install --no-cache-dir /srv/worker
RUN python -m playwright install --with-deps chromium \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin elara \
    && mkdir -p /var/lib/elara/fetch \
    && chown -R elara:elara /ms-playwright /var/lib/elara/fetch

COPY infrastructure/docker/container-entrypoint.py /container-entrypoint.py

USER elara

ENTRYPOINT ["python", "/container-entrypoint.py"]

CMD ["python", "-m", "celery", "-A", "app.celery_app:celery_app", "worker", "--loglevel=info", "--queues=verification.quick,verification.standard,verification.deep"]
