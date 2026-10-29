"""In-process mock of an OpenAI-compatible endpoint for tests.

A threaded ``http.server`` implementing ``POST {root}/chat/completions`` and
``GET {root}/models``. A script string starting with ``"!"`` means the *next*
request with that marker in some message content fails first; see
:class:`MockEndpoint` below for the simpler, pytest-fixture-driven version.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class MockEndpoint:
    """Scriptable fake chat endpoint.

    Pass either simple ``responses`` (list of per-request completion content
    strings, reused cyclically) or ``completion_fn`` to compute replies from
    the parsed request payload.
    """

    def __init__(self, responses=None, completion_fn=None, http_status=200):
        self.requests = []
        self.responses = list(responses or [])
        self.completion_fn = completion_fn
        self.http_status = http_status
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self):
        host, port = self._server.server_address
        return "http://127.0.0.1:%d/v1" % port

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _json(self, code, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.startswith("/v1/models"):
                    self._json(
                        200,
                        {"data": [{"id": "mock-model"}]},
                    )
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                if not self.path.startswith("/v1/chat/completions"):
                    self._json(404, {"error": "not found"})
                    return
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length).decode("utf-8")
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    self._json(400, {"error": "bad json"})
                    return
                outer.requests.append(payload)
                if outer.http_status != 200:
                    self._json(outer.http_status, {"error": "boom"})
                    return
                if outer.completion_fn is not None:
                    content, status = outer.completion_fn(payload)
                    if status != 200:
                        self._json(status, {"error": str(content)[:200]})
                        return
                else:
                    if not outer.responses:
                        self._json(500, {"error": "no script"})
                        return
                    content = outer.responses[len(outer.requests) - 1]
                    status = 200
                self._json(
                    200,
                    {
                        "choices": [
                            {"message": {"role": "assistant", "content": content}}
                        ]
                    },
                )

        return Handler

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    @staticmethod
    def content_of(request_payload):
        """Last non-system message content of a recorded request payload."""
        messages = [
            m for m in request_payload.get("messages", []) if m["role"] != "system"
        ]
        return messages[-1]["content"] if messages else ""
