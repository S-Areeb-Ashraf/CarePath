import pytest
from app.auth import hash_password, verify_password, create_token, verify_token, TokenError


def test_password_round_trip():
    stored = hash_password('S3cure!Pass')
    assert stored != 'S3cure!Pass'
    assert verify_password('S3cure!Pass', stored)
    assert not verify_password('wrong', stored)
    assert not verify_password('S3cure!Pass', 'garbage')


def test_password_hashes_are_salted():
    assert hash_password('same') != hash_password('same')


def test_token_round_trip():
    token = create_token('PAT-001', 'a@b.com', 'secret-key', 1)
    payload = verify_token(token, 'secret-key')
    assert payload['patient_reference'] == 'PAT-001'
    assert payload['email'] == 'a@b.com'
    assert payload['exp'] > 0


def test_token_rejects_wrong_secret():
    token = create_token('PAT-001', 'a@b.com', 'secret-key', 1)
    with pytest.raises(TokenError):
        verify_token(token, 'other-secret')


def test_token_rejects_malformed():
    with pytest.raises(TokenError):
        verify_token('not-a-token', 'secret-key')
    with pytest.raises(TokenError):
        verify_token('v1.abc.def', 'secret-key')


def test_expired_token_rejected():
    token = create_token('PAT-001', 'a@b.com', 'secret-key', -1)
    with pytest.raises(TokenError, match='expired'):
        verify_token(token, 'secret-key')
