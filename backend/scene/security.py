"""Password hashing, session tokens, rate limits, two-step sign-in codes and request checks. Standard library only."""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlsplit

# scrypt at the strength OWASP recommends (N = 2^17, 128 MB of memory per hash). A hash is stored with its own
# settings, so the passwords hashed with the older, weaker settings still sign in and are upgraded when they do.
SCRYPT = {"n": 2 ** 17, "r": 8, "p": 1, "dklen": 32}
OLD_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
MAX_PASSWORD = 1024   # a longer one is refused before it is hashed, so nobody can make the server hash megabytes
MAX_FAILURES = 5
LOCK_SECONDS = 60


def _scrypt(password, salt, params):
    memory = 128 * params["n"] * params["r"] * 2   # what scrypt needs, with room to spare
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, maxmem=memory, **params)


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, SCRYPT)
    return "scrypt${}${}${}${}${}".format(SCRYPT["n"].bit_length() - 1, SCRYPT["r"], SCRYPT["p"], salt.hex(), digest.hex())


def _parse(stored):
    """(settings, salt, digest) of a stored hash: "scrypt$<log2 n>$<r>$<p>$<salt>$<digest>", or the older
    "scrypt$<salt>$<digest>" made with OLD_SCRYPT."""
    parts = stored.split("$")
    if parts[0] != "scrypt":
        raise ValueError(stored[:10])
    if len(parts) == 3:
        return OLD_SCRYPT, bytes.fromhex(parts[1]), bytes.fromhex(parts[2])
    log_n, r, p, salt, digest = parts[1:]
    if not (10 <= int(log_n) <= 20 and 1 <= int(r) <= 32 and 1 <= int(p) <= 16):
        raise ValueError(stored[:20])
    return {"n": 2 ** int(log_n), "r": int(r), "p": int(p), "dklen": 32}, bytes.fromhex(salt), bytes.fromhex(digest)


def verify_password(password, stored):
    if len(password) > MAX_PASSWORD:
        return False
    try:
        params, salt, digest = _parse(stored)
        return hmac.compare_digest(_scrypt(password, salt, params), digest)
    except (ValueError, TypeError):
        return False


def needs_rehash(stored):
    try:
        return _parse(stored)[0] != SCRYPT
    except (ValueError, TypeError):
        return True


# A hash of nothing anybody knows. Signing in with an email that has no account checks the password against it,
# so a wrong email takes as long as a wrong password and the answer time does not tell which emails have accounts.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def new_token():
    return secrets.token_urlsafe(32)


def token_hash(token):
    """Sessions are stored by hash, so a copy of the database can't be used to sign in."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def client_address(request):
    """The visitor's address. Through the Cloudflare Tunnel every request arrives from this machine and the
    visitor's own address is in a header; the header is believed only then, since anyone else could write it."""
    host = request.client.host if request.client else ""
    forwarded = request.headers.get("cf-connecting-ip", "").strip()[:64]
    return forwarded if forwarded and host in ("127.0.0.1", "::1") else host


def is_https(request):
    """Whether the browser reached the app over https: directly, or through the tunnel on this machine, which says so
    in a header."""
    if request.url.scheme in ("https", "wss"):
        return True
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1") and request.headers.get("x-forwarded-proto", "").lower() == "https"


def same_origin(request):
    """False when a browser sent this request from another site, which is how a forged request arrives (CSRF, or a
    WebSocket opened by another page). Browsers say where a request came from in Sec-Fetch-Site; an older one
    that does not is judged by its Origin. A request with neither (a script, a test) did not come from a page."""
    site = request.headers.get("sec-fetch-site")
    if site:
        return site in ("same-origin", "none")
    origin = request.headers.get("origin")
    if origin is None:
        return True
    return urlsplit(origin).netloc.lower() == request.headers.get("host", "").lower()


class LoginThrottle:
    """Blocks a key (email + address) for a minute after five wrong passwords."""

    def __init__(self):
        self.failures = {}

    def blocked(self, key):
        return len(self._recent(key)) >= MAX_FAILURES

    def fail(self, key):
        # Forget every key whose failures are all over a minute old, so the table does not grow for ever.
        for old in [k for k in self.failures if k != key]:
            self._recent(old)
        self.failures[key] = self._recent(key) + [time.time()]

    def _recent(self, key):
        recent = [t for t in self.failures.get(key, []) if time.time() - t < LOCK_SECONDS]
        if recent:
            self.failures[key] = recent
        else:
            self.failures.pop(key, None)
        return recent

    def clear(self, key):
        self.failures.pop(key, None)


class RateLimit:
    """At most `limit` requests per key in a sliding window of `seconds`. Kept in memory: one app process."""

    def __init__(self):
        self.hits = {}
        self.swept = time.time()

    def allow(self, key, limit, seconds):
        """Count a request; False when the key is over its limit (the request is then not counted)."""
        now = time.time()
        if now - self.swept > 300:   # forget keys with nothing recent, so the table does not grow for ever
            self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < 3600}
            self.swept = now
        recent = [t for t in self.hits.get(key, ()) if now - t < seconds]
        if len(recent) >= limit:
            self.hits[key] = recent
            return False
        self.hits[key] = recent + [now]
        return True

    def retry_after(self, key, seconds):
        recent = self.hits.get(key) or [time.time()]
        return max(1, int(recent[0] + seconds - time.time()) + 1)


# ---------------------------------------------------------------- two-step sign-in (TOTP, RFC 6238)

TOTP_STEP = 30
TOTP_DIGITS = 6


def new_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def totp_code(secret, step):
    key = base64.b32decode(secret)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** TOTP_DIGITS).zfill(TOTP_DIGITS)


def check_totp(secret, code, last_step=0, now=None):
    """The time step a code belongs to (the one before, now or the one after, for a phone clock a little off), or
    None. A step at or before `last_step` was already used, so a code that was seen cannot be used again."""
    code = "".join(str(code or "").split())
    if not code.isdigit() or len(code) != TOTP_DIGITS:
        return None
    current = int((now or time.time()) // TOTP_STEP)
    for step in (current - 1, current, current + 1):
        if step > last_step and hmac.compare_digest(totp_code(secret, step), code):
            return step
    return None


def totp_uri(secret, email, issuer="Scene.ai"):
    """The address an authenticator app takes: as a link on a phone, or the secret typed in by hand."""
    return "otpauth://totp/{}:{}?secret={}&issuer={}&digits={}&period={}".format(
        quote(issuer), quote(email), secret, quote(issuer), TOTP_DIGITS, TOTP_STEP)


def new_recovery_codes(count=8):
    """One-time codes for when the phone is lost. Shown once; only their hashes are kept."""
    return ["{}-{}".format(secrets.token_hex(3), secrets.token_hex(3)) for _ in range(count)]


def recovery_hash(code):
    return hashlib.sha256("".join(str(code).lower().split()).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- uploaded files

# The first bytes of each kind of file the studio takes. A file is judged by what it is, not by its name.
def sniff(data):
    """"image", "video", "audio", "video/audio" (an MP4-family file that may be either) or None."""
    head = data[:16]
    if head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xff\xd8\xff"):
        return "image"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio"
    if head[4:8] == b"ftyp":
        return "video/audio"   # MP4, MOV and M4A all start this way
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/audio"   # Matroska: MKV or WebM, which may hold only sound
    if head.startswith((b"ID3", b"fLaC", b"OggS")) or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "audio"         # MP3 (with or without a tag), FLAC, Ogg, AAC (ADTS)
    return None


def content_matches(kind, data):
    """Whether bytes that arrived named as `kind` are a file of that kind."""
    found = sniff(data)
    return found is not None and kind in found.split("/")
