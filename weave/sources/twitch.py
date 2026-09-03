"""Twitch, for the live bar.

Logging in uses the device code grant, which is the flow meant for a client
that cannot keep a secret. Weave asks Twitch for a code, opens the browser at
the address Twitch hands back, and waits. That address already contains the
code, so there is nothing to copy or type, and what comes back includes a
refresh token, so it is asked once and not again.

Two parameter names differ from the usual spelling of this flow and were
confirmed against the live endpoint rather than assumed. The device request
takes `scopes` rather than `scope`, and waiting for approval is reported as
HTTP 400 with the message `authorization_pending` rather than as a success.

A client id is public by design. There is no client secret anywhere in this
flow, so nothing here needs protecting except the tokens, which live in the
state directory with owner only permissions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import requests

from .. import __version__

DEVICE_URL = "https://id.twitch.tv/oauth2/device"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
HELIX = "https://api.twitch.tv/helix"

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
SCOPES = "user:read:follows"
USER_AGENT = f"Weave/{__version__} (+https://github.com/Tobias2909/Weave)"

# Helix takes a hundred logins or ids per request.
BATCH = 100
TIMEOUT_S = 20.0


class TwitchError(RuntimeError):
    pass


class AuthPending(TwitchError):
    """Waiting for the approval in the browser."""


class NeedsLogin(TwitchError):
    """No usable token. The login has to be done again."""


@dataclass(frozen=True)
class DeviceLogin:
    device_code: str
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str
    obtained_at: int = field(default_factory=lambda: int(time.time()))

    def as_dict(self) -> dict:
        return {"access_token": self.access_token, "refresh_token": self.refresh_token,
                "obtained_at": self.obtained_at}

    @classmethod
    def from_dict(cls, data: dict) -> "Tokens | None":
        access = str(data.get("access_token") or "")
        refresh = str(data.get("refresh_token") or "")
        if not access or not refresh:
            return None
        return cls(access, refresh, int(data.get("obtained_at") or 0))


@dataclass(frozen=True)
class Stream:
    login: str
    display_name: str
    title: str
    game: str
    viewers: int
    started_at: str
    thumbnail_url: str

    @property
    def key(self) -> str:
        return f"twitch:{self.login}"


def _session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


# ---- logging in ---------------------------------------------------------

def start_login(client_id: str, session: requests.Session | None = None) -> DeviceLogin:
    session = session or _session()
    response = session.post(DEVICE_URL, timeout=TIMEOUT_S,
                            data={"client_id": client_id, "scopes": SCOPES})
    if response.status_code != 200:
        raise TwitchError(_message(response, "could not start the login"))
    body = response.json()
    return DeviceLogin(
        device_code=body["device_code"],
        user_code=body["user_code"],
        verification_uri=body["verification_uri"],
        interval=int(body.get("interval") or 5),
        expires_in=int(body.get("expires_in") or 1800),
    )


def poll_login(client_id: str, device_code: str,
               session: requests.Session | None = None) -> Tokens:
    """One attempt. Raises AuthPending until the browser approval happens."""
    session = session or _session()
    response = session.post(TOKEN_URL, timeout=TIMEOUT_S, data={
        "client_id": client_id, "device_code": device_code,
        "grant_type": DEVICE_GRANT, "scopes": SCOPES})
    if response.status_code == 200:
        body = response.json()
        return Tokens(body["access_token"], body.get("refresh_token", ""))
    message = _message(response, "")
    if "authorization_pending" in message or response.status_code == 400:
        raise AuthPending(message or "waiting for approval")
    raise TwitchError(message or f"login failed with status {response.status_code}")


def refresh(client_id: str, refresh_token: str,
            session: requests.Session | None = None) -> Tokens:
    session = session or _session()
    response = session.post(TOKEN_URL, timeout=TIMEOUT_S, data={
        "client_id": client_id, "refresh_token": refresh_token,
        "grant_type": "refresh_token"})
    if response.status_code != 200:
        raise NeedsLogin(_message(response, "the stored login is no longer valid"))
    body = response.json()
    return Tokens(body["access_token"], body.get("refresh_token", refresh_token))


def validate(access_token: str, session: requests.Session | None = None) -> dict:
    """Who the token belongs to. Also the cheapest way to find the account id,
    which the followed streams call needs."""
    session = session or _session()
    response = session.get(VALIDATE_URL, timeout=TIMEOUT_S,
                           headers={"Authorization": f"OAuth {access_token}"})
    if response.status_code != 200:
        raise NeedsLogin(_message(response, "the stored login is no longer valid"))
    return response.json()


def _message(response: requests.Response, fallback: str) -> str:
    try:
        body = response.json()
    except ValueError:
        return fallback or response.text[:160]
    return str(body.get("message") or body.get("error") or fallback)


# ---- reading ------------------------------------------------------------

def parse_streams(payload: dict) -> list[Stream]:
    """Turn a Helix streams response into rows. Tolerates a missing field
    rather than dropping the stream, since only the login really matters."""
    streams: list[Stream] = []
    for item in payload.get("data") or []:
        login = str(item.get("user_login") or "").lower()
        if not login:
            continue
        streams.append(Stream(
            login=login,
            display_name=str(item.get("user_name") or login),
            title=str(item.get("title") or ""),
            game=str(item.get("game_name") or ""),
            viewers=int(item.get("viewer_count") or 0),
            started_at=str(item.get("started_at") or ""),
            thumbnail_url=_sized(str(item.get("thumbnail_url") or "")),
        ))
    return streams


def _sized(template: str, width: int = 440, height: int = 248) -> str:
    """Stream thumbnails come back with size placeholders in the address."""
    if not template:
        return ""
    return template.replace("{width}", str(width)).replace("{height}", str(height))


class Client:
    """Authenticated Helix calls, refreshing the token when it has expired."""

    def __init__(self, client_id: str, tokens: Tokens,
                 on_tokens=None, session: requests.Session | None = None) -> None:
        self.client_id = client_id
        self.tokens = tokens
        self._on_tokens = on_tokens
        self._session = session or _session()

    def _headers(self) -> dict:
        return {"Client-Id": self.client_id,
                "Authorization": f"Bearer {self.tokens.access_token}"}

    def _get(self, path: str, params: list[tuple[str, Any]]) -> dict:
        for attempt in (0, 1):
            response = self._session.get(f"{HELIX}/{path}", params=params,
                                         headers=self._headers(), timeout=TIMEOUT_S)
            if response.status_code == 200:
                return response.json()
            # An expired token is the one failure worth retrying, and only once.
            if response.status_code == 401 and attempt == 0:
                self.tokens = refresh(self.client_id, self.tokens.refresh_token, self._session)
                if self._on_tokens:
                    self._on_tokens(self.tokens)
                continue
            if response.status_code == 401:
                raise NeedsLogin(_message(response, "the stored login is no longer valid"))
            raise TwitchError(_message(response, f"request failed with status {response.status_code}"))
        raise TwitchError("request failed")

    def account_id(self) -> str:
        return str(validate(self.tokens.access_token, self._session).get("user_id") or "")

    def followed_streams(self, user_id: str) -> list[Stream]:
        streams: list[Stream] = []
        cursor = None
        while True:
            params = [("user_id", user_id), ("first", BATCH)]
            if cursor:
                params.append(("after", cursor))
            payload = self._get("streams/followed", params)
            streams.extend(parse_streams(payload))
            cursor = (payload.get("pagination") or {}).get("cursor")
            if not cursor:
                return streams

    def streams_for(self, logins: list[str]) -> list[Stream]:
        """Live status for particular channels, for the ones tracked by hand
        rather than followed."""
        streams: list[Stream] = []
        for start in range(0, len(logins), BATCH):
            chunk = logins[start:start + BATCH]
            if not chunk:
                continue
            payload = self._get("streams", [("user_login", login) for login in chunk])
            streams.extend(parse_streams(payload))
        return streams

    def follows(self, user_id: str) -> list[tuple[str, str]]:
        """Every channel the account follows, as login and display name."""
        found: list[tuple[str, str]] = []
        cursor = None
        while True:
            params = [("user_id", user_id), ("first", BATCH)]
            if cursor:
                params.append(("after", cursor))
            payload = self._get("channels/followed", params)
            for item in payload.get("data") or []:
                login = str(item.get("broadcaster_login") or "").lower()
                if login:
                    found.append((login, str(item.get("broadcaster_name") or login)))
            cursor = (payload.get("pagination") or {}).get("cursor")
            if not cursor:
                return found
