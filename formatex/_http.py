"""Low-level HTTP transport for FormaTex API."""

from __future__ import annotations

import httpx

from formatex.exceptions import (
    FormaTexError,
    AuthenticationError,
    CompilationError,
    RateLimitError,
    PlanLimitError,
)


class HTTPClient:
    """Thin wrapper around httpx providing auth and error mapping."""

    def __init__(self, api_key: str, base_url: str, timeout: float):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    # -- helpers ---------------------------------------------------------------

    def get_json(self, path: str) -> dict:
        resp = self._client.get(path)
        self._raise_for_status(resp)
        return resp.json()

    def get_bytes(self, path: str) -> bytes:
        """GET a binary response (e.g. PDF download)."""
        resp = self._client.get(path)
        self._raise_for_status(resp)
        return resp.content

    def post_json(self, path: str, body: dict) -> dict:
        """POST with JSON body, expect JSON back."""
        resp = self._client.post(
            path,
            json=body,
            headers={"Accept": "application/json"},
        )
        self._raise_for_status(resp)
        return resp.json()

    def post_bytes(self, path: str, body: dict) -> bytes:
        """POST with JSON body, get raw bytes back (e.g. DOCX)."""
        resp = self._client.post(path, json=body)
        self._raise_for_status(resp)
        return resp.content

    def put_raw(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        """PUT raw bytes (e.g. file upload); expects 204 No Content."""
        resp = self._client.put(path, content=data, headers={"Content-Type": content_type})
        self._raise_for_status(resp)

    def post_empty(self, path: str, body: dict) -> None:
        """POST JSON body without expecting a JSON response (handles 200/204)."""
        resp = self._client.post(path, json=body)
        self._raise_for_status(resp)

    def delete_json(self, path: str) -> dict:
        """DELETE, expect JSON back (or empty body on 204)."""
        resp = self._client.delete(path)
        self._raise_for_status(resp)
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    # -- error mapping ---------------------------------------------------------

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.is_success:
            return

        try:
            body = resp.json()
        except Exception:
            body = {}
        msg = body.get("error", resp.text[:200])

        if resp.status_code == 401:
            raise AuthenticationError(msg, status_code=401, body=body)
        if resp.status_code == 403:
            raise PlanLimitError(msg, status_code=403, body=body)
        if resp.status_code == 422:
            raise CompilationError(
                msg,
                log=body.get("log", ""),
                status_code=422,
                body=body,
            )
        if resp.status_code == 429:
            retry = float(resp.headers.get("Retry-After", "0"))
            raise RateLimitError(msg, retry_after=retry, status_code=429, body=body)

        raise FormaTexError(msg, status_code=resp.status_code, body=body)
