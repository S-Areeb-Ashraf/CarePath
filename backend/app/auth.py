"""Authentication utilities. Stdlib only: hashlib PBKDF2 password hashing and
HMAC-signed stateless tokens. Provider and framework agnostic."""
import base64
import hashlib
import hmac
import json
import os
import time

PBKDF2_ITERATIONS = 120_000
TOKEN_VERSION = 'v1'


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), base64.b64decode(salt_b64), int(iterations))
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


def _sign(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(secret.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()


def create_token(patient_reference: str, email: str, secret: str, ttl_hours: int) -> str:
    payload = json.dumps({
        'patient_reference': patient_reference,
        'email': email,
        'exp': int(time.time()) + ttl_hours * 3600,
    }, separators=(',', ':'), sort_keys=True).encode('utf-8')
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip('=')
    signature = _sign(f'{TOKEN_VERSION}.{encoded}'.encode('utf-8'), secret)
    return f'{TOKEN_VERSION}.{encoded}.{signature}'


class TokenError(Exception):
    pass


def verify_token(token: str, secret: str) -> dict:
    try:
        version, encoded, signature = token.split('.')
    except ValueError as exc:
        raise TokenError('Malformed token.') from exc
    if version != TOKEN_VERSION:
        raise TokenError('Unsupported token version.')
    if not hmac.compare_digest(_sign(f'{version}.{encoded}'.encode('utf-8'), secret), signature):
        raise TokenError('Invalid token signature.')
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    except (ValueError, json.JSONDecodeError) as exc:
        raise TokenError('Malformed token payload.') from exc
    if not isinstance(payload, dict) or int(payload.get('exp', 0)) < time.time():
        raise TokenError('Token expired.')
    if not payload.get('patient_reference') or not payload.get('email'):
        raise TokenError('Token missing identity.')
    return payload
