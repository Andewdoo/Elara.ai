from app.config import Settings
from app.redis_client import worker_liveness_key
from elara_worker.worker_liveness import refresh_worker_liveness


class RecordingRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    def set(self, key: str, value: str, *, ex: int) -> bool:
        self.values[key] = value
        self.expirations[key] = ex
        return True


def test_worker_readiness_signal_is_transient_and_uses_a_bounded_ttl():
    redis_client = RecordingRedis()
    settings = Settings(environment="test", worker_liveness_ttl_seconds=45)

    assert refresh_worker_liveness(settings=settings, redis_client=redis_client) is True
    assert redis_client.values == {worker_liveness_key(): "ready"}
    assert redis_client.expirations == {worker_liveness_key(): 45}
