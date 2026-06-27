import os


def _embedding_dimension() -> int:
    raw_value = os.getenv("PASSAGE_EMBEDDING_DIMENSION", "1536")
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("PASSAGE_EMBEDDING_DIMENSION must be an integer") from exc
    if value <= 0:
        raise RuntimeError("PASSAGE_EMBEDDING_DIMENSION must be positive")
    return value


PASSAGE_EMBEDDING_DIMENSION = _embedding_dimension()
