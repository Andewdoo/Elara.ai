"""Adapt host-development database settings for the Compose network."""

from __future__ import annotations

import os
import sys

from sqlalchemy.engine import make_url


_HOST_DEVELOPMENT_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _rewrite_database_host_for_compose(database_url: str) -> str:
    """Point local database URLs at the Postgres Compose service, preserving credentials."""

    url = make_url(database_url)
    if url.host not in _HOST_DEVELOPMENT_DATABASE_HOSTS:
        return database_url

    return url.set(host=os.environ.get("ELARA_DOCKER_DATABASE_HOST", "postgres")).render_as_string(
        hide_password=False
    )


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        os.environ["DATABASE_URL"] = _rewrite_database_host_for_compose(database_url)

    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
