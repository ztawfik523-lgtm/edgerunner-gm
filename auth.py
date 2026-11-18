"""Role-based authentication (admin vs user) and signed session tokens."""
from __future__ import annotations

import base64
from collections import deque
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any

from turnloop import default_settings_path, read_settings_doc, write_settings_doc

_TOKEN_TTL_SECONDS = 7 * 24 * 3600
_MAX_LOGIN_FAILURES = 12
_LOGIN_WINDOW_SECONDS = 60.0
_AUTH_LOCK = threading.RLock()


class AuthError(ValueError):
    """Raised on invalid credentials or auth payload."""


class AuthRateLimitError(ValueError):
    """Raised after repeated failed login attempts."""


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

    def __init__(self, settings_path: Path | None = None, *, room_pin: str = ""):
        self._explicit_settings_path = settings_path.expanduser() if settings_path is not None else None
        self.room_pin = (room_pin or "").strip()
        self._failures: dict[str, deque[float]] = {}
        self._rate_lock = threading.Lock()

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
        with _AUTH_LOCK:
            doc = read_settings_doc(self.settings_path)
            auth = dict(doc.get("auth")) if isinstance(doc.get("auth"), dict) else {}
            next_auth = mutator(auth)
            doc["auth"] = next_auth
            write_settings_doc(doc, self.settings_path)
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
            q = self._failures.setdefault(bucket, deque())
            while q and now - q[0] > _LOGIN_WINDOW_SECONDS:
                q.popleft()
            if len(q) >= _MAX_LOGIN_FAILURES:
                raise AuthRateLimitError("Too many failed sign-in attempts; wait 60 seconds and try again.")

    def _record_failure(self, bucket: str) -> None:
        now = time.monotonic()
        with self._rate_lock:
            q = self._failures.setdefault(bucket, deque())
            while q and now - q[0] > _LOGIN_WINDOW_SECONDS:
                q.popleft()
            q.append(now)

    def _clear_failures(self, bucket: str) -> None:
        with self._rate_lock:
            self._failures.pop(bucket, None)

    def issue_token(self, username: str, role: str) -> str:
        secret, version = self._ensure_secret_and_version()
        payload = {
            "sub": username,
            "role": role,
            "v": version,
            "exp": int(time.time()) + _TOKEN_TTL_SECONDS,
        }
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
            if not hmac.compare_digest(sig, expected_sig):
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
            return {"username": str(payload.get("sub") or role), "role": role}
        except (ValueError, json.JSONDecodeError, TypeError):
            return None

    def resolve_session(self, token: str | None = None, pin: str | None = None) -> dict[str, Any]:
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
                "admin_configured": self.is_admin_configured(),
                "user_configured": self.is_user_configured(),
                "user_passcode_configured": bool(auth.get("user_passcode_hash") or self.room_pin),
                "allow_guest_users": self.allow_guest_users(),
                "allow_self_signup": self.allow_self_signup(),
                "can_bootstrap": self.can_bootstrap(),
            }

        supplied_pin = (pin or "").strip()
        if supplied_pin:
            if self.room_pin and hmac.compare_digest(supplied_pin, self.room_pin):
                return {
                    "auth_enabled": enabled,
                    "pin_only_mode": pin_only,
                    "authenticated": True,
                    "role": "user",
                    "username": "player",
                    "admin_configured": self.is_admin_configured(),
                    "user_configured": self.is_user_configured(),
                    "user_passcode_configured": bool(auth.get("user_passcode_hash") or self.room_pin),
                    "allow_guest_users": self.allow_guest_users(),
                    "allow_self_signup": self.allow_self_signup(),
                    "can_bootstrap": self.can_bootstrap(),
                }
            passcode_hash = auth.get("user_passcode_hash")
            if isinstance(passcode_hash, str) and verify_password(supplied_pin, passcode_hash):
                return {
                    "auth_enabled": enabled,
                    "pin_only_mode": pin_only,
                    "authenticated": True,
                    "role": "user",
                    "username": "player",
                    "admin_configured": self.is_admin_configured(),
                    "user_configured": self.is_user_configured(),
                    "user_passcode_configured": True,
                    "allow_guest_users": self.allow_guest_users(),
                    "allow_self_signup": self.allow_self_signup(),
                    "can_bootstrap": self.can_bootstrap(),
                }

        if not enabled:
            role = "open"
            authenticated = True
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
            if (not uname_low or uname_low == adm_u.lower()) and hmac.compare_digest(pw, adm_p):
                self._clear_failures(bucket)
                return {"token": self.issue_token(adm_u, "admin"), "role": "admin", "username": adm_u, "expires_in": _TOKEN_TTL_SECONDS}

        env_user = self._env_user()
        if env_user is not None and mode_clean in {"auto", "user"}:
            usr_u, usr_p = env_user
            if (not uname_low or uname_low == usr_u.lower()) and hmac.compare_digest(pw, usr_p):
                self._clear_failures(bucket)
                return {"token": self.issue_token(usr_u, "user"), "role": "user", "username": usr_u, "expires_in": _TOKEN_TTL_SECONDS}

        # 2. Check saved named accounts.
        if uname_low and uname_low in accounts:
            acc = accounts[uname_low]
            acc_role = acc["role"]
            if mode_clean in {"auto", acc_role} and verify_password(pw, acc["password_hash"]):
                self._clear_failures(bucket)
                return {
                    "token": self.issue_token(acc["username"], acc_role),
                    "role": acc_role,
                    "username": acc["username"],
                    "expires_in": _TOKEN_TTL_SECONDS,
                }
        elif not uname_low:
            # Allow password-only Admin login when only one saved admin account exists.
            admin_accs = [a for a in accounts.values() if a["role"] == "admin"]
            if mode_clean == "admin" and len(admin_accs) == 1 and verify_password(pw, admin_accs[0]["password_hash"]):
                acc = admin_accs[0]
                self._clear_failures(bucket)
                return {
                    "token": self.issue_token(acc["username"], "admin"),
                    "role": "admin",
                    "username": acc["username"],
                    "expires_in": _TOKEN_TTL_SECONDS,
                }

        # 3. Check shared User passcode / room PIN when signing in as User.
        if mode_clean in {"auto", "user"}:
            passcode_hash = auth.get("user_passcode_hash")
            label = uname or "player"
            if isinstance(passcode_hash, str) and verify_password(pw, passcode_hash):
                self._clear_failures(bucket)
                return {"token": self.issue_token(label, "user"), "role": "user", "username": label, "expires_in": _TOKEN_TTL_SECONDS}
            if self.room_pin and hmac.compare_digest(pw, self.room_pin):
                self._clear_failures(bucket)
                return {"token": self.issue_token(label, "user"), "role": "user", "username": label, "expires_in": _TOKEN_TTL_SECONDS}

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
        if self.is_admin_configured():
            raise AuthError("Admin is already configured; sign in as Admin to manage access.")
        adm_name = (admin_username or "admin").strip()
        if not adm_name or len(adm_name) > 40:
            raise AuthError("Admin username must be 1-40 characters")
        adm_hash = hash_password(admin_password)
        usr_name = (user_username or "").strip()
        usr_hash = hash_password(user_password) if user_password else None
        if usr_hash and not usr_name:
            usr_name = "player"
        passcode_hash = hash_password(user_passcode) if user_passcode else None
        now_iso = datetime.now(timezone.utc).isoformat()

        def _write(cur: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(cur.get("secret"), str) or len(cur["secret"]) < 32:
                cur["secret"] = secrets.token_hex(32)
            cur["token_version"] = int(cur.get("token_version") or 1)
            accs = self._saved_accounts(cur)
            accs[adm_name.lower()] = {
                "username": adm_name,
                "role": "admin",
                "password_hash": adm_hash,
                "created_at": now_iso,
            }
            if usr_hash and usr_name.lower() != adm_name.lower():
                accs[usr_name.lower()] = {
                    "username": usr_name,
                    "role": "user",
                    "password_hash": usr_hash,
                    "created_at": now_iso,
                }
            cur["accounts"] = accs
            if passcode_hash:
                cur["user_passcode_hash"] = passcode_hash
            cur["allow_guest_users"] = bool(allow_guest_users)
            cur["allow_self_signup"] = bool(allow_self_signup)
            return cur

        self._update_auth_section(_write)
        return {
            "token": self.issue_token(adm_name, "admin"),
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
        revoke_sessions = bool(payload.get("revoke_sessions") or payload.get("revoke_all_tokens"))
        has_guest = "allow_guest_users" in payload and payload["allow_guest_users"] is not None
        has_signup = "allow_self_signup" in payload and payload["allow_self_signup"] is not None

        def _apply(cur: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(cur.get("secret"), str) or len(cur["secret"]) < 32:
                cur["secret"] = secrets.token_hex(32)
            cur["token_version"] = int(cur.get("token_version") or 1)
            accs = self._saved_accounts(cur)
            if username:
                if len(username) > 40:
                    raise AuthError("Username must be at most 40 characters")
                target_role = str(role or "user").strip().lower()
                if target_role not in {"admin", "user"}:
                    raise AuthError("Account role must be 'admin' or 'user'")
                key = username.lower()
                existing = accs.get(key)
                if password:
                    pw_hash = hash_password(str(password))
                elif existing:
                    pw_hash = existing["password_hash"]
                else:
                    raise AuthError("Password is required when creating a new account")
                accs[key] = {
                    "username": username,
                    "role": target_role,
                    "password_hash": pw_hash,
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
            if revoke_sessions:
                cur["secret"] = secrets.token_hex(32)
                cur["token_version"] = int(cur.get("token_version") or 1) + 1
            return cur

        self._update_auth_section(_apply)
        return self.list_accounts()

    def delete_account(self, username: str) -> dict[str, Any]:
        target = (username or "").strip().lower()
        if not target:
            raise AuthError("Username is required")
        env_admin = self._env_admin()

        def _remove(cur: dict[str, Any]) -> dict[str, Any]:
            accs = self._saved_accounts(cur)
            if target not in accs:
                raise AuthError(f"Saved account not found: {username}")
            if accs[target]["role"] == "admin":
                other_admins = [k for k, v in accs.items() if k != target and v["role"] == "admin"]
                if not other_admins and env_admin is None:
                    raise AuthError("Cannot delete the last admin account")
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
        if not isinstance(password, str) or len(password) < 4 or len(password) > 256:
            raise AuthError("Password must be 4-256 characters")
        key = uname.lower()
        env_admin = self._env_admin()
        env_user = self._env_user()
        if (env_admin and key == env_admin[0].lower()) or (env_user and key == env_user[0].lower()):
            raise AuthError("That username is already taken.")
        pw_hash = hash_password(password)
        now_iso = datetime.now(timezone.utc).isoformat()

        def _create(cur: dict[str, Any]) -> dict[str, Any]:
            accs = self._saved_accounts(cur)
            if key in accs:
                raise AuthError("That username is already taken.")
            accs[key] = {
                "username": uname,
                "role": "user",
                "password_hash": pw_hash,
                "created_at": now_iso,
            }
            cur["accounts"] = accs
            return cur

        self._update_auth_section(_create)
        self._clear_failures(bucket)
        return {
            "token": self.issue_token(uname, "user"),
            "role": "user",
            "username": uname,
            "expires_in": _TOKEN_TTL_SECONDS,
        }
