"""Password hashing, session tokens and a small login throttle. Standard library only."""

import hashlib
import hmac
import secrets
import time

SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
MAX_FAILURES = 5
LOCK_SECONDS = 60


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **SCRYPT)
    return "scrypt${}${}".format(salt.hex(), digest.hex())


def verify_password(password, stored):
    try:
        scheme, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        check = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), **SCRYPT)
        return hmac.compare_digest(check, bytes.fromhex(digest))
    except ValueError:
        return False


def new_token():
    return secrets.token_urlsafe(32)


def token_hash(token):
    """Sessions are stored by hash, so a copy of the database can't be used to sign in."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class LoginThrottle:
    """Blocks a key (email + address) for a minute after five wrong passwords."""

    def __init__(self):
        self.failures = {}

    def blocked(self, key):
        recent = [t for t in self.failures.get(key, []) if time.time() - t < LOCK_SECONDS]
        self.failures[key] = recent
        return len(recent) >= MAX_FAILURES

    def fail(self, key):
        self.failures.setdefault(key, []).append(time.time())

    def clear(self, key):
        self.failures.pop(key, None)
