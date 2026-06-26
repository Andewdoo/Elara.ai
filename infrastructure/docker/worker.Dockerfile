FROM python:3.12-slim

WORKDIR /app

COPY apps/worker /app

CMD ["python", "-m", "celery", "-A", "tasks.app", "worker", "--loglevel=info"]

