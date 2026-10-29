"""Minimal OpenAI-compatible chat-completions client.

Configured by base URL only — no API keys, ever. The endpoint root is
something like ``http://localhost:11434/v1``; this module appends
``/chat/completions`` for POSTs and ``/models`` for capability probing.
"""

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class EndpointError(Exception):
    """Raised when the endpoint cannot be reached or answers nonsensically."""


class Endpoint:
    """A single OpenAI-compatible chat endpoint, addressed by URL alone."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 120.0,
        user_agent: str = "llm-json-extractor/0.1.0",
    ) -> None:
        if "://" not in base_url:
            raise EndpointError(
                "base-url must include a scheme, e.g. http://localhost:11434/v1"
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.user_agent = user_agent

    # -- HTTP plumbing -------------------------------------------------

    def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = self.base_url + path
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                pass
            raise EndpointError(
                "endpoint returned HTTP %s for %s%s"
                % (exc.code, url, (" — " + detail) if detail else "")
            ) from exc
        except urllib.error.URLError as exc:
            raise EndpointError(
                "cannot reach endpoint %s (%s)" % (url, exc.reason)
            ) from exc
        except OSError as exc:
            raise EndpointError(
                "cannot reach endpoint %s (%s)" % (url, exc)
            ) from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EndpointError(
                "endpoint returned non-JSON HTTP body" " (%s)" % exc
            ) from exc

    # -- OpenAI-compatible surface ------------------------------------

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.0,
        response_json: bool = False,
    ) -> str:
        """POST /chat/completions and return the first message content.

        Raises :class:`EndpointError` on transport/HTTP problems and raises
        :class:`UnsupportedJsonMode` when the server rejects
        ``response_format`` and *response_json* was requested.
        """
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_json:
            payload["response_format"] = {"type": "json_object"}
        try:
            data = self._post_json("/chat/completions", payload)
        except EndpointError as exc:
            text = str(exc)
            if response_json and (
                "HTTP 400" in text or "HTTP 422" in text
            ) and "response_format" in json.dumps(payload):
                # Some servers reject response_format outright; the caller
                # may downgrade, so signal that distinctly.
                raise UnsupportedJsonMode(str(exc)) from exc
            raise
        try:
            choices = data["choices"]
            message = choices[0]["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise EndpointError(
                "unexpected completion shape from endpoint: %r" % (exc,)
            ) from exc
        if not isinstance(content, str):
            raise EndpointError("completion content is not a string")
        return content

    def models(self) -> List[str]:
        """GET-style probe via POST-less request: list available model ids."""
        url = self.base_url + "/models"
        request = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": self.user_agent}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            raise EndpointError("cannot reach endpoint %s (%s)" % (url, exc)) from exc
        items = data.get("data", []) if isinstance(data, dict) else []
        return [item.get("id", "") for item in items if isinstance(item, dict)]


class UnsupportedJsonMode(EndpointError):
    """The endpoint rejected ``response_format``; caller may downgrade."""
