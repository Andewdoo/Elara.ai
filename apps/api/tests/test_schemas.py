from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.verifications import InputType, VerificationCreateRequest


@pytest.mark.parametrize(
    ("input_type", "field", "value"),
    [
        (InputType.CLAIM, "text", "A testable claim"),
        (InputType.ARTICLE_TEXT, "text", "Article body"),
        (InputType.PARAPHRASE, "text", "A paraphrased statement"),
        (InputType.ARTICLE_URL, "url", "https://example.com/story"),
        (InputType.QUOTE, "quote", "An exact quote"),
        (InputType.UPLOADED_DOCUMENT, "upload_id", uuid4()),
    ],
)
def test_verification_request_accepts_the_required_payload(input_type, field, value):
    request = VerificationCreateRequest(input_type=input_type, **{field: value})
    assert request.input_type == input_type


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/story",
        "http://127.0.0.1/story",
        "https://user:pass@example.com",
        "https://intranet/story",
        "https://example.com:8443/story",
    ],
)
def test_verification_request_rejects_unsafe_direct_urls(url: str):
    with pytest.raises(ValidationError):
        VerificationCreateRequest(input_type=InputType.ARTICLE_URL, url=url)


def test_verification_request_requires_matching_payload():
    with pytest.raises(ValidationError):
        VerificationCreateRequest(input_type=InputType.QUOTE, text="not a quote payload")


def test_verification_request_rejects_whitespace_and_conflicting_targets():
    with pytest.raises(ValidationError):
        VerificationCreateRequest(input_type=InputType.CLAIM, text="   ")
    with pytest.raises(ValidationError):
        VerificationCreateRequest(
            input_type=InputType.ARTICLE_URL,
            url="https://example.com/story",
            text="unrelated hidden text",
        )
