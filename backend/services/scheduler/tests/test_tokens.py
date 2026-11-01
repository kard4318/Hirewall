# Tests for signed booking-link tokens
from datetime import datetime, timedelta, timezone

import pytest

from services.scheduler.conversation.tokens import (
    TokenError,
    TokenSecretError,
    create_token,
    token_id,
    verify_token,
)

NOW = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)
SECRET = "test-secret-please-change"


def test_roundtrip() -> None:
    token = create_token("cand-1", "job-1", 72, NOW, secret=SECRET)
    payload = verify_token(token, NOW, secret=SECRET)
    assert (payload.candidate_id, payload.job_id) == ("cand-1", "job-1")
    assert payload.expires_at == NOW + timedelta(hours=72)


def test_tampered_payload_rejected() -> None:
    token = create_token("cand-1", "job-1", 72, NOW, secret=SECRET)
    forged = create_token("cand-2", "job-1", 72, NOW, secret=SECRET).split(".")[0] + "." + token.split(".")[1]
    with pytest.raises(TokenError, match="signature"):
        verify_token(forged, NOW, secret=SECRET)


def test_expired_rejected() -> None:
    token = create_token("cand-1", "job-1", 1, NOW, secret=SECRET)
    with pytest.raises(TokenError, match="expired"):
        verify_token(token, NOW + timedelta(hours=2), secret=SECRET)


def test_wrong_secret_rejected() -> None:
    token = create_token("cand-1", "job-1", 72, NOW, secret=SECRET)
    with pytest.raises(TokenError):
        verify_token(token, NOW, secret="another-secret")


@pytest.mark.parametrize("bad", ["", "abc", "a.b.c", "é.é", "x" * 600])
def test_bad_format_rejected(bad: str) -> None:
    with pytest.raises(TokenError):
        verify_token(bad, NOW, secret=SECRET)


def test_missing_secret_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCHEDULER_TOKEN_SECRET", raising=False)
    with pytest.raises(TokenSecretError, match="SCHEDULER_TOKEN_SECRET"):
        create_token("cand-1", "job-1", 72, NOW)


def test_token_id_is_stable_16_hex() -> None:
    token = create_token("cand-1", "job-1", 72, NOW, secret=SECRET)
    assert token_id(token) == token_id(token)
    assert len(token_id(token)) == 16 and int(token_id(token), 16) >= 0
