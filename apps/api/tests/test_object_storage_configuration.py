from app.config import Settings
from app.services.object_storage import _s3_client_options


def test_instance_role_credentials_are_not_overridden():
    settings = Settings(
        _env_file=None,
        environment="test",
        s3_endpoint_url="https://s3.us-east-1.amazonaws.com",
        s3_region="us-east-1",
        s3_force_path_style=False,
        s3_access_key_id="",
        s3_secret_access_key="",
    )

    options = _s3_client_options(settings)

    assert "aws_access_key_id" not in options
    assert "aws_secret_access_key" not in options
