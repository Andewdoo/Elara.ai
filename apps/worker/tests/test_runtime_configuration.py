from app.config import Settings
from graph.runtime import _s3_client_options, _uses_s3_snapshot_store


def test_staging_uses_instance_role_credential_chain_for_s3():
    settings = Settings(
        _env_file=None,
        environment="test",
        s3_endpoint_url="https://s3.us-east-1.amazonaws.com",
        s3_region="us-east-1",
        s3_force_path_style=False,
        s3_access_key_id=None,
        s3_secret_access_key=None,
    )
    settings.environment = "staging"

    options = _s3_client_options(settings)

    assert _uses_s3_snapshot_store(settings) is True
    assert "aws_access_key_id" not in options
    assert "aws_secret_access_key" not in options


def test_local_explicit_s3_credentials_are_preserved():
    settings = Settings(
        _env_file=None,
        environment="test",
        s3_access_key_id="access",
        s3_secret_access_key="secret",
    )

    options = _s3_client_options(settings)

    assert _uses_s3_snapshot_store(settings) is True
    assert options["aws_access_key_id"] == "access"
    assert options["aws_secret_access_key"] == "secret"
