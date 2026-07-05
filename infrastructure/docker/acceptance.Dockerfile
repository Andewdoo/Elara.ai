FROM python:3.12-slim

WORKDIR /srv

COPY apps/api /srv/api
RUN pip install --no-cache-dir "/srv/api[dev]"

COPY apps/worker /srv/worker
RUN pip install --no-cache-dir "/srv/worker[dev]"

COPY acceptance /srv/acceptance

CMD ["pytest", "-q", "-s", "/srv/acceptance/test_full_stack.py"]

