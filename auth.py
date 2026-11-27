"""Role-based authentication (admin vs user) and signed session tokens."""
from __future__ import annotations

import base64
from collections import deque
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
import uuid
from typing import Any, Callable, ContextManager

from index_lock import index_lock
from turnloop import _SETTINGS_LOCK, default_settings_path, read_settings_doc, write_settings_doc

_TOKEN_TTL_SECONDS = 7 * 24 * 3600
_MAX_LOGIN_FAILURES = 12
_LOGIN_WINDOW_SECONDS = 60.0
_MAX_PIN_FAILURES = 20
_PIN_WINDOW_SECONDS = 60.0
_MAX_RATE_LIMIT_BUCKETS = 4096

# Every shared-passcode / room-PIN session acts as this one identity. It is
# reserved so no saved account can share it (and thus its characters).
SHARED_USERNAME = "player"

# Context manager factory run inside an account rename/delete: receives
# (old_username, new_username or None for deletion) and must commit its own
# changes only when the with-block exits cleanly.
OwnerTransfer = Callable[[str, "str | None"], ContextManager[Any]]


class AuthError(ValueError):
    """Raised on invalid credentials or auth payload."""


class AuthRateLimitError(ValueError):
    """Raised after repeated failed login attempts."""


def _secret_eq(supplied: str, expected: str) -> bool:
    """Constant-time comparison that accepts any Unicode text."""
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def _check_account_name(username: str) -> None:
    if username.lower() == SHARED_USERNAME:
        raise AuthError(f"The username '{SHARED_USERNAME}' is reserved for shared-passcode players.")


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 4:
        raise AuthError("Password must be at least 4 characters long")
    if len(password) > 256:
        raise AuthError("Password must be at most 256 characters long")
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    if not isinstance(password, str) or not isinstance(encoded, str):
        return False
    parts = encoded.split("$")
    if len(parts) != 3 or parts[0] != "scrypt":
        return False
    try:
        salt = bytes.fromhex(parts[1])
        expected = bytes.fromhex(parts[2])
    except ValueError:
        return False
    actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=len(expected))
    return hmac.compare_digest(actual, expected)


class AuthManager:
    """Manages Admin/User accounts, shared passcodes, and HMAC session tokens."""

    def __init__(self, settings_path: Path | None = None, *, room_pin: str = "", allow_open: bool = True):
        self._explicit_settings_path = settings_path.expanduser() if settings_path is not None else None
        self.room_pin = (room_pin or "").strip()
        # Unconfigured auth grants "open" (admin-equivalent) access only on loopback binds.
        self.allow_open = allow_open
        self._failures: dict[str, deque[float]] = {}
        self._rate_lock = threading.Lock()
        self._pin_failures: dict[str, deque[float]] = {}
        self._pin_rate_lock = threading.Lock()

    @property
    def settings_path(self) -> Path:
        return self._explicit_settings_path or default_settings_path()

    def _env_admin(self) -> tuple[str, str] | None:
        pw = os.environ.get("REDGM_ADMIN_PASS", "").strip()
        if not pw:
            return None
        user = (os.environ.get("REDGM_ADMIN_USER", "admin") or "admin").strip()
        return user, pw

    def _env_user(self) -> tuple[str, str] | None:
        pw = os.environ.get("REDGM_USER_PASS", "").strip()
        if not pw:
            return None
        user = (os.environ.get("REDGM_USER_USER", "player") or "player").strip()
        return user, pw

    def _read_auth_section(self) -> dict[str, Any]:
        doc = read_settings_doc(self.settings_path)
        raw = doc.get("auth")
        return dict(raw) if isinstance(raw, dict) else {}

    def _update_auth_section(self, mutator) -> dict[str, Any]:
        with _SETTINGS_LOCK:
            path = self.settings_path
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with index_lock(path):
                doc = read_settings_doc(path)
                auth = dict(doc.get("auth")) if isinstance(doc.get("auth"), dict) else {}
                next_auth = mutator(auth)
                doc["auth"] = next_auth
                write_settings_doc(doc, path)
                return next_auth

    def _ensure_secret_and_version(self) -> tuple[str, int]:
        auth = self._read_auth_section()
        secret = auth.get("secret")
        version = auth.get("token_version")
        if isinstance(secret, str) and len(secret) >= 32 and isinstance(version, int) and version >= 1:
            return secret, version

        def _init(cur: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(cur.get("secret"), str) or len(cur["secret"]) < 32:
                cur["secret"] = secrets.token_hex(32)
            if not isinstance(cur.get("token_version"), int) or cur["token_version"] < 1:
                cur["token_version"] = 1
            cur.setdefault("accounts", {})
            cur.setdefault("allow_guest_users", False)
            return cur

        updated = self._update_auth_section(_init)
        return str(updated["secret"]), int(updated["token_version"])

    def _saved_accounts(self, auth: dict[str, Any]) -> dict[str, dict[str, Any]]:
        raw = auth.get("accounts")
        if not isinstance(raw, dict):
            return {}
        clean: dict[str, dict[str, Any]] = {}
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, dict) and v.get("role") in {"admin", "user"} and v.get("password_hash"):
                clean[k.strip().lower()] = v
        return clean

    def is_admin_configured(self) -> bool:
        if self._env_admin() is not None:
            return True
        accounts = self._saved_accounts(self._read_auth_section())
        return any(a.get("role") == "admin" for a in accounts.values())

    def is_user_configured(self) -> bool:
        if self._env_user() is not None or self.room_pin:
            return True
        auth = self._read_auth_section()
        if auth.get("user_passcode_hash"):
            return True
        accounts = self._saved_accounts(auth)
        return any(a.get("role") == "user" for a in accounts.values())

    def has_account_auth(self) -> bool:
        """True when Admin or saved User account auth (not just legacy room_pin) is enabled."""
        if self._env_admin() is not None or self._env_user() is not None:
            return True
        auth = self._read_auth_section()
        return bool(self._saved_accounts(auth) or auth.get("user_passcode_hash"))

    def is_pin_only_mode(self) -> bool:
        return bool(self.room_pin) and not self.has_account_auth()

    def allow_guest_users(self) -> bool:
        return bool(self._read_auth_section().get("allow_guest_users", False))

    def allow_self_signup(self) -> bool:
        return bool(self._read_auth_section().get("allow_self_signup", True))

    def auth_enabled(self) -> bool:
        return self.has_account_auth() or bool(self.room_pin)

    def can_bootstrap(self) -> bool:
        return not self.is_admin_configured()

    def _check_rate_limit(self, bucket: str) -> None:
        now = time.monotonic()
        with self._rate_lock:
            if bucket not in self._failures and len(self._failures) >= _MAX_RATE_LIMIT_BUCKETS:
                # Evict the oldest bucket (empty buckets have timestamp 0)
                oldest = min(self._failures, key=lambda key: self._failures[key][0] if self._failures[key] else 0)
                self._failures.pop(oldest, None)
            q = self._failures.setdefault(bucket, deque())
            while q and now - q[0] > _LOGIN_WINDOW_SECONDS:
                q.popleft()
            if len(q) >= _MAX_LOGIN_FAILURES:
                raise AuthRateLimitError("Too many failed sign-in attempts; wait 60 seconds and try again.")

    def _record_failure(self, bucket: str) -> None:
        now = time.monotonic()
        with self._rate_lock:
            if bucket not in self._failures and len(self._failures) >= _MAX_RATE_LIMIT_BUCKETS:
                oldest = min(self._failures, key=lambda key: self._failures[key][0] if self._failures[key] else 0)
                self._failures.pop(oldest, None)
            q = self._failures.setdefault(bucket, deque())
            while q and now - q[0] > _LOGIN_WINDOW_SECONDS:
                q.popleft()
            q.append(now)

    def _clear_failures(self, bucket: str) -> None:
        with self._rate_lock:
            self._failures.pop(bucket, None)

    def _check_pin_rate_limit(self, bucket: str) -> None:
        now = time.monotonic()
        with self._pin_rate_lock:
            if bucket not in self._pin_failures and len(self._pin_failures) >= _MAX_RATE_LIMIT_BUCKETS:
                oldest = min(self._pin_failures, key=lambda key: self._pin_failures[key][0] if self._pin_failures[key] else 0)
                self._pin_failures.pop(oldest, None)
            q = self._pin_failures.setdefault(bucket, deque())
            while q and now - q[0] > _PIN_WINDOW_SECONDS:
                q.popleft()
            if len(q) >= _MAX_PIN_FAILURES:
                raise AuthRateLimitError("Too many PIN attempts; wait 60 seconds and try again.")

    def _record_pin_failure(self, bucket: str) -> None:
        now = time.monotonic()
        with self._pin_rate_lock:
            if bucket not in self._pin_failures and len(self._pin_failures) >= _MAX_RATE_LIMIT_BUCKETS:
                oldest = min(self._pin_failures, key=lambda key: self._pin_failures[key][0] if self._pin_failures[key] else 0)
                self._pin_failures.pop(oldest, None)
            q = self._pin_failures.setdefault(bucket, deque())
            while q and now - q[0] > _PIN_WINDOW_SECONDS:
                q.popleft()
            q.append(now)

    def _clear_pin_failures(self, bucket: str) -> None:
        with self._pin_rate_lock:
            self._pin_failures.pop(bucket, None)

    def issue_token(
        self,
        username: str,
        role: str,
        *,
        token_kind: str,
        account_version: int | None = None,
        credential_binding: str | None = None,
        account_id: str | None = None,
    ) -> str:
        secret, version = self._ensure_secret_and_version()
        payload = {
            "sub": username,
            "role": role,
            "v": version,
            "kind": token_kind,
            "exp": int(time.time()) + _TOKEN_TTL_SECONDS,
        }
        if token_kind == "account":
            payload["av"] = account_version
            if account_id:
                payload["aid"] = account_id
        elif token_kind in {"environment", "shared"}:
            if not isinstance(credential_binding, str) or not credential_binding:
                raise AuthError("Credential binding is required for this token kind")
            payload["cb"] = hmac.new(
                secret.encode("utf-8"), credential_binding.encode("utf-8"), hashlib.sha256
            ).hexdigest()
        body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        sig = _b64e(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
        return f"{body}.{sig}"

    def verify_token(self, token: str | None) -> dict[str, Any] | None:
        if not token or not isinstance(token, str) or "." not in token:
            return None
        try:
            body, sig = token.strip().split(".", 1)
            secret, version = self._ensure_secret_and_version()
            expected_sig = _b64e(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
            if not _secret_eq(sig, expected_sig):
                return None
            payload = json.loads(_b64d(body).decode("utf-8"))
            if not isinstance(payload, dict):
                return None
            if int(payload.get("exp") or 0) < int(time.time()):
                return None
            if int(payload.get("v") or 0) != version:
                return None
            role = payload.get("role")
            if role not in {"admin", "user"}:
                return None
            username = str(payload.get("sub") or role)
            token_kind = payload.get("kind")
            if token_kind == "account":
                account = self._saved_accounts(self._read_auth_section()).get(username.strip().lower())
                account_version = payload.get("av")
                token_account_id = payload.get("aid")
                if (
                    account is None
                    or account.get("role") != role
                    or type(account_version) is not int
                    or type(account.get("token_version", 1)) is not int
                    or account.get("token_version", 1) != account_version
                    or not isinstance(token_account_id, str)
                    or not token_account_id
                    or account.get("account_id") != token_account_id
                ):
                    return None
            elif token_kind == "environment":
                configured_match = next((
                    (configured, configured_role)
                    for configured, configured_role in (
                        (self._env_admin(), "admin"),
                        (self._env_user(), "user"),
                    )
                    if configured is not None
                    and configured[0].casefold() == username.casefold()
                    and configured_role == role
                ), None)
                if (
                    configured_match is None
                    or not hmac.compare_digest(
                        str(payload.get("cb") or ""),
                        hmac.new(
                            secret.encode("utf-8"),
                            f"environment:{configured_match[0][1]}".encode("utf-8"),
                            hashlib.sha256,
                        ).hexdigest(),
                    )
                ):
                    return None
            elif token_kind == "shared":
                if role != "user":
                    return None
                auth = self._read_auth_section()
                bindings = []
                if isinstance(auth.get("user_passcode_hash"), str):
                    bindings.append(f"passcode:{auth['user_passcode_hash']}")
                if self.room_pin:
                    bindings.append(f"room-pin:{self.room_pin}")
                if not any(
                    hmac.compare_digest(
                        str(payload.get("cb") or ""),
                        hmac.new(secret.encode("utf-8"), binding.encode("utf-8"), hashlib.sha256).hexdigest(),
                    )
                    for binding in bindings
                ):
                    return None
            else:
                # Reject legacy untyped tokens so deleted or changed accounts'
                # pre-upgrade sessions cannot evade per-account revocation.
                return None
            return {"username": username, "role": role, "kind": token_kind}
        except (ValueError, json.JSONDecodeError, TypeError):
            return None

    def resolve_session(self, token: str | None = None, pin: str | None = None, pin_bucket: str | None = None) -> dict[str, Any]:
        verified = self.verify_token(token)
        auth = self._read_auth_section()
        pin_only = self.is_pin_only_mode()
        enabled = self.auth_enabled()

        if verified is not None:
            return {
                "auth_enabled": enabled,
                "pin_only_mode": pin_only,
                "authenticated": True,
                "role": verified["role"],
                "username": verified["username"],
                "token_kind": verified["kind"],
                "admin_configured": self.is_admin_configured(),
                "user_configured": self.is_user_configured(),
                "user_passcode_configured": bool(auth.get("user_passcode_hash") or self.room_pin),
                "allow_guest_users": self.allow_guest_users(),
                "allow_self_signup": self.allow_self_signup(),
                "can_bootstrap": self.can_bootstrap(),
            }

        supplied_pin = (pin or "").strip()
        if supplied_pin:
            bucket = pin_bucket or "pin"
            try:
                self._check_pin_rate_limit(bucket)
            except AuthRateLimitError as exc:
                return {
                    "auth_enabled": enabled,
                    "pin_only_mode": pin_only,
                    "authenticated": False,
                    "role": "anon",
                    "username": None,
                    "token_kind": None,
                    "admin_configured": self.is_admin_configured(),
                    "user_configured": self.is_user_configured(),
                    "user_passcode_configured": bool(auth.get("user_passcode_hash") or self.room_pin),
                    "allow_guest_users": self.allow_guest_users(),
                    "allow_self_signup": self.allow_self_signup(),
                    "can_bootstrap": self.can_bootstrap(),
                    "detail": str(exc),
                }
            if self.room_pin and _secret_eq(supplied_pin, self.room_pin):
                self._clear_pin_failures(bucket)
                return {
                    "auth_enabled": enabled,
                    "pin_only_mode": pin_only,
                    "authenticated": True,
                    "role": "user",
                    "username": SHARED_USERNAME,
                    "token_kind": "shared",
                    "admin_configured": self.is_admin_configured(),
                    "user_configured": self.is_user_configured(),
                    "user_passcode_configured": bool(auth.get("user_passcode_hash") or self.room_pin),
                    "allow_guest_users": self.allow_guest_users(),
                    "allow_self_signup": self.allow_self_signup(),
                    "can_bootstrap": self.can_bootstrap(),
                }
            passcode_hash = auth.get("user_passcode_hash")
            if isinstance(passcode_hash, str) and verify_password(supplied_pin, passcode_hash):
                self._clear_pin_failures(bucket)
                return {
                    "auth_enabled": enabled,
                    "pin_only_mode": pin_only,
                    "authenticated": True,
                    "role": "user",
                    "username": SHARED_USERNAME,
                    "token_kind": "shared",
                    "admin_configured": self.is_admin_configured(),
                    "user_configured": self.is_user_configured(),
                    "user_passcode_configured": True,
                    "allow_guest_users": self.allow_guest_users(),
                    "allow_self_signup": self.allow_self_signup(),
                    "can_bootstrap": self.can_bootstrap(),
                }
            self._record_pin_failure(bucket)

        if not enabled:
            role = "open" if self.allow_open else "anon"
            authenticated = self.allow_open
        elif pin_only:
            role = "user"
            authenticated = False
        elif self.allow_guest_users():
            role = "user"
            authenticated = True
        else:
            role = "anon"
            authenticated = False

        return {
            "auth_enabled": enabled,
            "pin_only_mode": pin_only,
            "authenticated": authenticated,
            "role": role,
            "username": None,
            "token_kind": None,
            "admin_configured": self.is_admin_configured(),
            "user_configured": self.is_user_configured(),
            "user_passcode_configured": bool(auth.get("user_passcode_hash") or self.room_pin),
            "allow_guest_users": self.allow_guest_users(),
            "allow_self_signup": self.allow_self_signup(),
            "can_bootstrap": self.can_bootstrap(),
        }

    def authenticate(
        self,
        *,
        mode: str = "auto",
        username: str = "",
        password: str = "",
        bucket: str = "default",
    ) -> dict[str, Any]:
        self._check_rate_limit(bucket)
        mode_clean = (mode or "auto").strip().lower()
        if mode_clean not in {"auto", "admin", "user"}:
            raise AuthError("Login mode must be 'admin', 'user', or 'auto'")
        uname = (username or "").strip()
        uname_low = uname.lower()
        pw = password or ""
        if not pw:
            self._record_failure(bucket)
            raise AuthError("Password or passcode is required")

        auth = self._read_auth_section()
        accounts = self._saved_accounts(auth)

        # 1. Check env-configured Admin / User accounts.
        env_admin = self._env_admin()
        if env_admin is not None and mode_clean in {"auto", "admin"}:
            adm_u, adm_p = env_admin
            if (not uname_low or uname_low == adm_u.lower()) and _secret_eq(pw, adm_p):
                self._clear_failures(bucket)
                return {"token": self.issue_token(adm_u, "admin", token_kind="environment",
                                                  credential_binding=f"environment:{adm_p}"),
                        "role": "admin", "username": adm_u, "expires_in": _TOKEN_TTL_SECONDS}

        env_user = self._env_user()
        if env_user is not None and mode_clean in {"auto", "user"}:
            usr_u, usr_p = env_user
            if (not uname_low or uname_low == usr_u.lower()) and _secret_eq(pw, usr_p):
                self._clear_failures(bucket)
                return {"token": self.issue_token(usr_u, "user", token_kind="environment",
                                                  credential_binding=f"environment:{usr_p}"),
                        "role": "user", "username": usr_u, "expires_in": _TOKEN_TTL_SECONDS}

        # 2. Check saved named accounts.
        if uname_low and uname_low in accounts:
            acc = accounts[uname_low]
            acc_role = acc["role"]
            if mode_clean in {"auto", acc_role} and verify_password(pw, acc["password_hash"]):
                self._clear_failures(bucket)
                return {
                    "token": self.issue_token(acc["username"], acc_role, token_kind="account",
                                              account_version=acc.get("token_version", 1),
                                              account_id=acc.get("account_id")),
                    "role": acc_role,
                    "username": acc["username"],
                    "expires_in": _TOKEN_TTL_SECONDS,
                }
        elif not uname_low:
            # Allow password-only Admin login when only one saved admin account exists.
            admin_accs = [(k, a) for k, a in accounts.items() if a["role"] == "admin"]
            if mode_clean == "admin" and len(admin_accs) == 1 and verify_password(pw, admin_accs[0][1]["password_hash"]):
                acc = admin_accs[0][1]
                self._clear_failures(bucket)
                return {
                    "token": self.issue_token(acc["username"], "admin", token_kind="account",
                                              account_version=acc.get("token_version", 1),
                                              account_id=acc.get("account_id")),
                    "role": "admin",
                    "username": acc["username"],
                    "expires_in": _TOKEN_TTL_SECONDS,
                }

        # 3. Check shared User passcode / room PIN when signing in as User. A
        # typed username is ignored: everyone holding the shared secret is the
        # same reserved identity, so nobody can claim another player's name.
        if mode_clean in {"auto", "user"}:
            passcode_hash = auth.get("user_passcode_hash")
            if isinstance(passcode_hash, str) and verify_password(pw, passcode_hash):
                self._clear_failures(bucket)
                return {"token": self.issue_token(SHARED_USERNAME, "user", token_kind="shared",
                                                  credential_binding=f"passcode:{passcode_hash}"),
                        "role": "user", "username": SHARED_USERNAME, "expires_in": _TOKEN_TTL_SECONDS}
            if self.room_pin and _secret_eq(pw, self.room_pin):
                self._clear_failures(bucket)
                return {"token": self.issue_token(SHARED_USERNAME, "user", token_kind="shared",
                                                  credential_binding=f"room-pin:{self.room_pin}"),
                        "role": "user", "username": SHARED_USERNAME, "expires_in": _TOKEN_TTL_SECONDS}

        self._record_failure(bucket)
        raise AuthError("Invalid username or password")

    def setup_initial(
        self,
        *,
        admin_username: str = "admin",
        admin_password: str,
        user_username: str = "",
        user_password: str = "",
        user_passcode: str = "",
        allow_guest_users: bool = False,
        allow_self_signup: bool = True,
    ) -> dict[str, Any]:
        adm_name = (admin_username or "admin").strip()
        if not adm_name or len(adm_name) > 40:
            raise AuthError("Admin username must be 1-40 characters")
        adm_hash = hash_password(admin_password)
        usr_name = (user_username or "").strip()
        usr_hash = hash_password(user_password) if user_password else None
        if usr_hash:
            if not usr_name or len(usr_name) > 40:
                raise AuthError("Player username must be 1-40 characters")
            _check_account_name(usr_name)
        passcode_hash = hash_password(user_passcode) if user_passcode else None
        now_iso = datetime.now(timezone.utc).isoformat()

        created_meta: dict[str, str] = {}

        def _write(cur: dict[str, Any]) -> dict[str, Any]:
            if self._env_admin() is not None or any(
                account.get("role") == "admin" for account in self._saved_accounts(cur).values()
            ):
                raise AuthError("Admin is already configured; sign in as Admin to manage access.")
            if not isinstance(cur.get("secret"), str) or len(cur["secret"]) < 32:
                cur["secret"] = secrets.token_hex(32)
            cur["token_version"] = int(cur.get("token_version") or 1)
            accs = self._saved_accounts(cur)
            adm_id = uuid.uuid4().hex
            accs[adm_name.lower()] = {
                "username": adm_name,
                "role": "admin",
                "password_hash": adm_hash,
                "token_version": 1,
                "account_id": adm_id,
                "created_at": now_iso,
            }
            if usr_hash and usr_name.lower() != adm_name.lower():
                usr_id = uuid.uuid4().hex
                accs[usr_name.lower()] = {
                    "username": usr_name,
                    "role": "user",
                    "password_hash": usr_hash,
                    "token_version": 1,
                    "account_id": usr_id,
                    "created_at": now_iso,
                }
            cur["accounts"] = accs
            if passcode_hash:
                cur["user_passcode_hash"] = passcode_hash
            cur["allow_guest_users"] = bool(allow_guest_users)
            cur["allow_self_signup"] = bool(allow_self_signup)
            created_meta["adm_id"] = adm_id
            return cur

        self._update_auth_section(_write)
        adm_id = created_meta["adm_id"]
        return {
            "token": self.issue_token(adm_name, "admin", token_kind="account", account_version=1, account_id=adm_id),
            "role": "admin",
            "username": adm_name,
            "expires_in": _TOKEN_TTL_SECONDS,
        }

    def list_accounts(self) -> dict[str, Any]:
        auth = self._read_auth_section()
        accounts = self._saved_accounts(auth)
        rows = [
            {
                "username": acc["username"],
                "role": acc["role"],
                "created_at": acc.get("created_at", ""),
                "source": "saved",
            }
            for acc in sorted(accounts.values(), key=lambda x: (0 if x["role"] == "admin" else 1, x["username"].lower()))
        ]
        env_admin = self._env_admin()
        if env_admin is not None:
            rows.insert(0, {"username": env_admin[0], "role": "admin", "created_at": "", "source": "env"})
        env_user = self._env_user()
        if env_user is not None:
            rows.append({"username": env_user[0], "role": "user", "created_at": "", "source": "env"})
        return {
            "accounts": rows,
            "allow_guest_users": bool(auth.get("allow_guest_users", False)),
            "allow_self_signup": bool(auth.get("allow_self_signup", True)),
            "user_passcode_configured": bool(auth.get("user_passcode_hash") or self.room_pin),
        }

    def update_access(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise AuthError("Payload must be an object")
        now_iso = datetime.now(timezone.utc).isoformat()
        username = str(payload.get("username") or "").strip()
        password = payload.get("password")
        role = payload.get("role")
        user_passcode = payload.get("user_passcode")
        clear_passcode = bool(payload.get("clear_user_passcode"))
        revoke_sessions = bool(payload.get("revoke_all_tokens"))
        has_guest = "allow_guest_users" in payload and payload["allow_guest_users"] is not None
        has_signup = "allow_self_signup" in payload and payload["allow_self_signup"] is not None

        def _apply(cur: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(cur.get("secret"), str) or len(cur["secret"]) < 32:
                cur["secret"] = secrets.token_hex(32)
            cur["token_version"] = int(cur.get("token_version") or 1)
            accs = self._saved_accounts(cur)
            shared_credential_changed = False
            if clear_passcode and cur.get("user_passcode_hash"):
                shared_credential_changed = True
            elif isinstance(user_passcode, str) and user_passcode.strip():
                shared_credential_changed = True
            if username:
                if len(username) > 40:
                    raise AuthError("Username must be at most 40 characters")
                key = username.lower()
                existing = accs.get(key)
                if existing is None:
                    _check_account_name(username)
                default_role = existing.get("role", "user") if existing else "user"
                target_role = str(role or default_role).strip().lower()
                if target_role not in {"admin", "user"}:
                    raise AuthError("Account role must be 'admin' or 'user'")
                if existing and existing.get("role") == "admin" and target_role != "admin":
                    other_admins = [k for k, v in accs.items() if k != key and v.get("role") == "admin"]
                    if not other_admins and self._env_admin() is None:
                        raise AuthError("Cannot demote the last admin account")
                account_security_changed = bool(existing and existing.get("role") != target_role)
                if password:
                    pw_hash = hash_password(str(password))
                    account_security_changed = account_security_changed or existing is not None
                elif existing:
                    pw_hash = existing["password_hash"]
                else:
                    raise AuthError("Password is required when creating a new account")
                account_version = int(existing.get("token_version", 1)) if existing else 1
                if account_security_changed:
                    account_version += 1
                accs[key] = {
                    "username": existing["username"] if existing else username,
                    "role": target_role,
                    "password_hash": pw_hash,
                    "token_version": account_version,
                    "account_id": existing.get("account_id") if existing else uuid.uuid4().hex,
                    "created_at": existing.get("created_at", now_iso) if existing else now_iso,
                }
                cur["accounts"] = accs
            if clear_passcode:
                cur.pop("user_passcode_hash", None)
            elif isinstance(user_passcode, str) and user_passcode.strip():
                cur["user_passcode_hash"] = hash_password(user_passcode.strip())
            if has_guest:
                cur["allow_guest_users"] = bool(payload["allow_guest_users"])
            if has_signup:
                cur["allow_self_signup"] = bool(payload["allow_self_signup"])
            if revoke_sessions or shared_credential_changed:
                cur["secret"] = secrets.token_hex(32)
                cur["token_version"] = int(cur.get("token_version") or 1) + 1
            return cur

        self._update_auth_section(_apply)
        return self.list_accounts()

    def delete_account(self, username: str, *, owner_transfer: OwnerTransfer | None = None) -> dict[str, Any]:
        """Delete a saved account; ``owner_transfer(name, None)`` releases its game ownership in the same commit."""
        target = (username or "").strip().lower()
        if not target:
            raise AuthError("Username is required")
        env_admin = self._env_admin()

        with ExitStack() as stack:
            def _remove(cur: dict[str, Any]) -> dict[str, Any]:
                accs = self._saved_accounts(cur)
                if target not in accs:
                    raise AuthError(f"Saved account not found: {username}")
                if accs[target]["role"] == "admin":
                    other_admins = [k for k, v in accs.items() if k != target and v["role"] == "admin"]
                    if not other_admins and env_admin is None:
                        raise AuthError("Cannot delete the last admin account")
                if owner_transfer is not None:
                    stack.enter_context(owner_transfer(accs[target]["username"], None))
                del accs[target]
                cur["accounts"] = accs
                return cur

            self._update_auth_section(_remove)
        return self.list_accounts()

    def register_user(self, *, username: str, password: str, bucket: str = "default") -> dict[str, Any]:
        self._check_rate_limit(bucket)
        if not self.is_admin_configured():
            raise AuthError("Admin setup is required before players can register.")
        if not self.allow_self_signup():
            raise AuthError("Player self-registration is disabled by the Admin.")
        uname = (username or "").strip()
        if not uname or len(uname) > 40:
            raise AuthError("Username must be 1-40 characters")
        _check_account_name(uname)
        if not isinstance(password, str) or len(password) < 4 or len(password) > 256:
            raise AuthError("Password must be 4-256 characters")
        key = uname.lower()
        env_admin = self._env_admin()
        env_user = self._env_user()
        if (env_admin and key == env_admin[0].lower()) or (env_user and key == env_user[0].lower()):
            raise AuthError("That username is already taken.")
        pw_hash = hash_password(password)
        now_iso = datetime.now(timezone.utc).isoformat()

        created_meta: dict[str, str] = {}

        def _create(cur: dict[str, Any]) -> dict[str, Any]:
            accs = self._saved_accounts(cur)
            if key in accs:
                raise AuthError("That username is already taken.")
            new_account_id = uuid.uuid4().hex
            accs[key] = {
                "username": uname,
                "role": "user",
                "password_hash": pw_hash,
                "token_version": 1,
                "account_id": new_account_id,
                "created_at": now_iso,
            }
            cur["accounts"] = accs
            created_meta["account_id"] = new_account_id
            return cur

        self._update_auth_section(_create)
        new_account_id = created_meta["account_id"]
        self._clear_failures(bucket)
        return {
            "token": self.issue_token(uname, "user", token_kind="account", account_version=1, account_id=new_account_id),
            "role": "user",
            "username": uname,
            "expires_in": _TOKEN_TTL_SECONDS,
        }

    def update_self_account(
        self,
        current_username: str,
        *,
        current_password: str,
        new_username: str | None = None,
        new_password: str | None = None,
        bucket: str = "default",
        owner_transfer: OwnerTransfer | None = None,
    ) -> dict[str, Any]:
        """Allow a signed-in saved account user (or admin) to update their own username and/or password.

        Wrong current passwords count against the sign-in rate limit for ``bucket``.
        On rename, ``owner_transfer(old, new)`` moves game ownership in the same commit.
        """
        self._check_rate_limit(bucket)
        cur_name = (current_username or "").strip()
        if not cur_name:
            raise AuthError("You must be signed in with a named account to update account settings.")
        if not isinstance(current_password, str) or not current_password:
            raise AuthError("Current password is required to confirm account changes.")

        cur_key = cur_name.lower()
        target_name = (new_username or "").strip() if isinstance(new_username, str) and new_username.strip() else cur_name
        if len(target_name) > 40:
            raise AuthError("Username must be 1-40 characters")
        target_key = target_name.lower()
        change_name = target_key != cur_key or target_name != cur_name
        if target_key != cur_key:
            _check_account_name(target_name)
        change_pw = isinstance(new_password, str) and len(new_password) > 0
        if not change_name and not change_pw:
            raise AuthError("Provide a new username or a new password.")
        if change_pw and (len(new_password) < 4 or len(new_password) > 256):
            raise AuthError("New password must be 4-256 characters")

        env_admin = self._env_admin()
        env_user = self._env_user()
        if (env_admin and cur_key == env_admin[0].lower()) or (env_user and cur_key == env_user[0].lower()):
            raise AuthError("Environment-configured accounts cannot be modified from the UI.")
        if change_name and ((env_admin and target_key == env_admin[0].lower()) or (env_user and target_key == env_user[0].lower())):
            raise AuthError("That username is already taken.")

        updated_meta: dict[str, Any] = {}
        wrong_password = False

        def _apply(cur: dict[str, Any]) -> dict[str, Any]:
            nonlocal wrong_password
            accs = self._saved_accounts(cur)
            entry = accs.get(cur_key)
            if entry is None:
                raise AuthError("Only saved accounts can update their username or password here.")
            if not verify_password(current_password, entry["password_hash"]):
                wrong_password = True
                raise AuthError("Current password is incorrect.")
            if target_key != cur_key and target_key in accs:
                raise AuthError("That username is already taken.")
            if change_name and owner_transfer is not None:
                stack.enter_context(owner_transfer(entry["username"], target_name))
            next_entry = dict(entry)
            next_entry["username"] = target_name
            if change_pw:
                next_entry["password_hash"] = hash_password(str(new_password))
            next_entry["token_version"] = int(entry.get("token_version", 1)) + 1
            if target_key != cur_key:
                next_entry["account_id"] = uuid.uuid4().hex
                del accs[cur_key]
            accs[target_key] = next_entry
            cur["accounts"] = accs
            updated_meta["username"] = target_name
            updated_meta["role"] = str(next_entry["role"])
            updated_meta["token_version"] = int(next_entry["token_version"])
            updated_meta["account_id"] = next_entry.get("account_id")
            return cur

        try:
            with ExitStack() as stack:
                self._update_auth_section(_apply)
        except AuthError:
            if wrong_password:
                self._record_failure(bucket)
            raise
        self._clear_failures(bucket)
        final_user = updated_meta["username"]
        final_role = updated_meta["role"]
        return {
            "token": self.issue_token(final_user, final_role, token_kind="account",
                                      account_version=updated_meta["token_version"],
                                      account_id=updated_meta.get("account_id")),
            "role": final_role,
            "username": final_user,
            "previous_username": cur_name,
            "expires_in": _TOKEN_TTL_SECONDS,
        }
