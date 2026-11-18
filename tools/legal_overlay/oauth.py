"""Local OAuth 2.1 + PKCE support for optional remote legal MCP providers.

The store lives under the ignored user profile.  Passwords are entered only in
the provider browser page; the overlay persists the dynamic client record and
OAuth tokens so both Codex and Claude can keep using the single local gateway.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import ssl
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import truststore


class OAuthError(ValueError):
    """Controlled OAuth error that must never contain credentials."""


def oauth_store_path(profile: Path, provider_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", provider_id):
        raise OAuthError("invalid provider id for OAuth storage")
    return profile / "settings" / "oauth" / f"{provider_id}.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OAuthError("local OAuth state is unreadable; run oauth-login again") from exc
    if not isinstance(value, dict):
        raise OAuthError("local OAuth state has an invalid shape; run oauth-login again")
    return value


def stored_access_token(path: Path) -> str:
    value = _read_json(path).get("tokens", {})
    if not isinstance(value, dict):
        return ""
    token = value.get("access_token")
    return token if isinstance(token, str) else ""


def stored_secret_values(path: Path) -> tuple[str, ...]:
    state = _read_json(path)
    values: list[str] = []
    for group_name in ("client", "tokens"):
        group = state.get(group_name, {})
        if not isinstance(group, dict):
            continue
        for key in ("client_secret", "access_token", "refresh_token"):
            value = group.get(key)
            if isinstance(value, str) and value:
                values.append(value)
    return tuple(values)


def _replace_with_retry(source: str | Path, target: Path) -> None:
    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    _replace_with_retry(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _safe_https_url(value: Any, *, label: str) -> str:
    url = str(value or "").strip()
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise OAuthError(f"provider published an unsafe {label} URL")
    return url


def _same_origin(left: str, right: str) -> bool:
    a, b = urlsplit(left), urlsplit(right)
    return (a.scheme, a.hostname, a.port or 443) == (b.scheme, b.hostname, b.port or 443)


def _ssl_context() -> ssl.SSLContext:
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _client(*, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        timeout=30.0,
        transport=transport,
        follow_redirects=False,
        verify=_ssl_context(),
    )


def _json_response(response: httpx.Response, *, action: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        value = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise OAuthError(f"OAuth {action} failed with HTTP {response.status_code}") from exc
    if not isinstance(value, dict):
        raise OAuthError(f"OAuth {action} returned an invalid response")
    return value


@dataclass(frozen=True)
class OAuthMetadata:
    resource: str
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str
    scope: str

    def as_dict(self) -> dict[str, str]:
        return {
            "resource": self.resource,
            "issuer": self.issuer,
            "authorization_endpoint": self.authorization_endpoint,
            "token_endpoint": self.token_endpoint,
            "registration_endpoint": self.registration_endpoint,
            "scope": self.scope,
        }


def discover_oauth(
    endpoint: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> OAuthMetadata:
    endpoint = _safe_https_url(endpoint, label="resource")
    payload = {
        "jsonrpc": "2.0",
        "id": "legal-overlay-oauth-discovery",
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "legal-overlay", "version": "0.11.2"},
        },
    }
    with _client(transport=transport) as client:
        probe = client.post(
            endpoint,
            json=payload,
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "MCP-Protocol-Version": "2025-06-18",
            },
        )
        challenge = probe.headers.get("www-authenticate", "")
        match = re.search(r'resource_metadata="([^"]+)"', challenge, re.IGNORECASE)
        if probe.status_code != 401 or not match:
            raise OAuthError("provider did not publish an MCP OAuth challenge")
        resource_metadata_url = _safe_https_url(match.group(1), label="resource metadata")
        if not _same_origin(endpoint, resource_metadata_url):
            raise OAuthError("OAuth resource metadata is outside the provider origin")
        resource_metadata = _json_response(
            client.get(resource_metadata_url),
            action="resource discovery",
        )
        resource = _safe_https_url(resource_metadata.get("resource"), label="resource")
        if resource.rstrip("/") != endpoint.rstrip("/"):
            raise OAuthError("OAuth resource metadata does not match the configured endpoint")
        servers = resource_metadata.get("authorization_servers", [])
        if not isinstance(servers, list) or not servers:
            raise OAuthError("provider did not publish an OAuth authorization server")
        issuer = _safe_https_url(servers[0], label="issuer").rstrip("/")
        metadata_url = issuer + "/.well-known/oauth-authorization-server"
        server_metadata = _json_response(
            client.get(metadata_url),
            action="authorization-server discovery",
        )

    published_issuer = _safe_https_url(server_metadata.get("issuer"), label="issuer").rstrip("/")
    if published_issuer != issuer:
        raise OAuthError("OAuth issuer metadata mismatch")
    scopes = resource_metadata.get("scopes_supported") or server_metadata.get("scopes_supported") or ["mcp"]
    if not isinstance(scopes, list) or not scopes:
        raise OAuthError("provider published an invalid OAuth scope list")
    scope = "mcp" if "mcp" in scopes else str(scopes[0])
    return OAuthMetadata(
        resource=resource,
        issuer=issuer,
        authorization_endpoint=_safe_https_url(
            server_metadata.get("authorization_endpoint"), label="authorization endpoint"
        ),
        token_endpoint=_safe_https_url(server_metadata.get("token_endpoint"), label="token endpoint"),
        registration_endpoint=_safe_https_url(
            server_metadata.get("registration_endpoint"), label="registration endpoint"
        ),
        scope=scope,
    )


def register_client(
    metadata: OAuthMetadata,
    redirect_uri: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    request = {
        "client_name": "Legal Knowledge Overlay",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    with _client(transport=transport) as client:
        registered = _json_response(
            client.post(metadata.registration_endpoint, json=request),
            action="dynamic client registration",
        )
    if not isinstance(registered.get("client_id"), str) or not registered["client_id"]:
        raise OAuthError("OAuth registration did not return a client id")
    return registered


def _token_request_data(
    client_info: dict[str, Any],
    values: dict[str, str],
) -> tuple[dict[str, str], httpx.BasicAuth | None]:
    method = str(client_info.get("token_endpoint_auth_method") or "none")
    client_id = str(client_info.get("client_id") or "")
    client_secret = str(client_info.get("client_secret") or "")
    if not client_id:
        raise OAuthError("local OAuth client state is incomplete")
    data = dict(values)
    auth: httpx.BasicAuth | None = None
    if method == "none":
        data["client_id"] = client_id
    elif method == "client_secret_post" and client_secret:
        data.update({"client_id": client_id, "client_secret": client_secret})
    elif method == "client_secret_basic" and client_secret:
        auth = httpx.BasicAuth(client_id, client_secret)
    else:
        raise OAuthError("provider selected an unsupported OAuth client authentication method")
    return data, auth


def request_tokens(
    metadata: OAuthMetadata,
    client_info: dict[str, Any],
    values: dict[str, str],
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    data, auth = _token_request_data(client_info, values)
    with _client(transport=transport) as client:
        tokens = _json_response(
            client.post(metadata.token_endpoint, data=data, auth=auth),
            action="token exchange",
        )
    if not isinstance(tokens.get("access_token"), str) or not tokens["access_token"]:
        raise OAuthError("OAuth token response did not contain an access token")
    return tokens


class _CallbackHandler(BaseHTTPRequestHandler):
    server: "_CallbackServer"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlsplit(self.path)
        if parsed.path != "/oauth/callback":
            self.send_error(404)
            return
        self.server.callback_query = parse_qs(parsed.query)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            "<html><body><h2>Legal Overlay: авторизация получена</h2>"
            "<p>Это окно можно закрыть и вернуться в Codex.</p></body></html>".encode("utf-8")
        )
        self.server.callback_event.set()

    def log_message(self, _format: str, *_args: Any) -> None:
        return


class _CallbackServer(ThreadingHTTPServer):
    callback_query: dict[str, list[str]] | None
    callback_event: threading.Event


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorize_provider(
    provider_id: str,
    endpoint: str,
    store_path: Path,
    *,
    timeout_seconds: int = 600,
    browser_open: Callable[[str], bool] = webbrowser.open,
) -> str:
    """Run one interactive login and persist only OAuth client/token state."""
    server = _CallbackServer(("127.0.0.1", 0), _CallbackHandler)
    server.callback_query = None
    server.callback_event = threading.Event()
    redirect_uri = f"http://127.0.0.1:{server.server_port}/oauth/callback"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        try:
            metadata = discover_oauth(endpoint)
            client_info = register_client(metadata, redirect_uri)
            verifier, challenge = _pkce_pair()
            state = secrets.token_urlsafe(32)
            query = {
                "response_type": "code",
                "client_id": str(client_info["client_id"]),
                "redirect_uri": redirect_uri,
                "scope": metadata.scope,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": metadata.resource,
            }
            authorization_url = metadata.authorization_endpoint + "?" + urlencode(query)
            if not browser_open(authorization_url):
                raise OAuthError("the system browser could not be opened")
            if not server.callback_event.wait(timeout_seconds):
                raise OAuthError("OAuth browser login timed out")
            callback = server.callback_query or {}
            if callback.get("error"):
                raise OAuthError("provider rejected OAuth authorization")
            returned_state = (callback.get("state") or [""])[0]
            returned_issuer = (callback.get("iss") or [""])[0].rstrip("/")
            code = (callback.get("code") or [""])[0]
            if not secrets.compare_digest(returned_state, state) or not code:
                raise OAuthError("OAuth callback validation failed")
            if returned_issuer and returned_issuer != metadata.issuer:
                raise OAuthError("OAuth callback issuer mismatch")
            tokens = request_tokens(
                metadata,
                client_info,
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "code_verifier": verifier,
                    "resource": metadata.resource,
                },
            )
            _write_json_atomic(
                store_path,
                {
                    "version": 1,
                    "provider_id": provider_id,
                    "endpoint": endpoint,
                    "metadata": metadata.as_dict(),
                    "client": client_info,
                    "tokens": tokens,
                    "obtained_at": int(time.time()),
                },
            )
        except httpx.HTTPError as exc:
            raise OAuthError("OAuth network request failed") from exc
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    return "authorized"


class OAuthTokenStore:
    def __init__(self, path: Path, provider_id: str, endpoint: str) -> None:
        self.path = path
        self.provider_id = provider_id
        self.endpoint = endpoint

    def _state(self) -> dict[str, Any]:
        state = _read_json(self.path)
        if state.get("provider_id") != self.provider_id or state.get("endpoint") != self.endpoint:
            raise OAuthError("local OAuth state does not match the configured provider")
        return state

    @staticmethod
    def _expired(state: dict[str, Any]) -> bool:
        tokens = state.get("tokens", {})
        if not isinstance(tokens, dict):
            return True
        expires_in = tokens.get("expires_in")
        obtained_at = state.get("obtained_at")
        try:
            lifetime = float(expires_in)
            obtained = float(obtained_at)
        except (TypeError, ValueError):
            return False
        return time.time() >= obtained + lifetime - 60

    def access_token(self, *, transport: httpx.BaseTransport | None = None) -> str:
        state = self._state()
        tokens = state.get("tokens", {})
        if not isinstance(tokens, dict):
            raise OAuthError("local OAuth token state is incomplete")
        if not self._expired(state):
            token = tokens.get("access_token")
            if isinstance(token, str) and token:
                return token
        refresh_token = tokens.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise OAuthError("OAuth access expired and no refresh token is available; run oauth-login again")
        try:
            metadata = OAuthMetadata(**state.get("metadata", {}))
        except (TypeError, ValueError) as exc:
            raise OAuthError("local OAuth metadata is incomplete; run oauth-login again") from exc
        client_info = state.get("client", {})
        if not isinstance(client_info, dict):
            raise OAuthError("local OAuth client state is incomplete")
        refreshed = request_tokens(
            metadata,
            client_info,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": metadata.scope,
                "resource": metadata.resource,
            },
            transport=transport,
        )
        if not refreshed.get("refresh_token"):
            refreshed["refresh_token"] = refresh_token
        state["tokens"] = refreshed
        state["obtained_at"] = int(time.time())
        _write_json_atomic(self.path, state)
        return str(refreshed["access_token"])

    def secret_values(self) -> tuple[str, ...]:
        return stored_secret_values(self.path)
