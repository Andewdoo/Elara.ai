FROM python:3.12-slim

WORKDIR /srv

COPY apps/api /srv/api
RUN pip install --no-cache-dir "/srv/api[dev]"

COPY apps/worker /srv/worker
RUN pip install --no-cache-dir "/srv/worker[dev]"

COPY acceptance /srv/acceptance

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin elara \
    && chown -R elara:elara /srv

USER elara

CMD ["pytest", "-q", "-s", "/srv/acceptance/test_full_stack.py"]
