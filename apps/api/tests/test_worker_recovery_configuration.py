from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_hosted_demo_worker_uses_a_bounded_restart_and_liveness_probe():
    compose = (REPO_ROOT / "docker-compose.public-beta.yml").read_text(encoding="utf-8")

    assert "restart: on-failure:3" in compose
    assert "celery -A app.celery_app:celery_app inspect ping" in compose
    assert "start_period: 20s" in compose
