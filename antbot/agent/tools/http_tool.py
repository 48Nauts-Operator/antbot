"""HTTP request tool for REST API testing."""

import json
from typing import Any

import httpx

from antbot.agent.tools.base import Tool

_MAX_BODY_CHARS = 10_000


class HttpTool(Tool):
    """Make HTTP requests for REST API testing."""

    @property
    def name(self) -> str:
        return "http_request"

    @property
    def description(self) -> str:
        return (
            "Make an HTTP request (GET, POST, PUT, DELETE, PATCH). "
            "Returns status code, headers, and body. For REST API testing."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                    "description": "HTTP method",
                },
                "url": {
                    "type": "string",
                    "description": "Request URL",
                },
                "headers": {
                    "type": "object",
                    "description": "Request headers as key-value pairs",
                },
                "body": {
                    "type": "string",
                    "description": "Request body (JSON string for POST/PUT/PATCH)",
                },
            },
            "required": ["method", "url"],
        }

    @property
    def category(self) -> str:
        return "devops"

    async def execute(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: str | None = None,
        **kwargs: Any,
    ) -> str:
        method = method.upper()
        if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
            return f"Error: Unsupported method '{method}'"

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                req_kwargs: dict[str, Any] = {}
                if headers:
                    req_kwargs["headers"] = headers
                if body and method in {"POST", "PUT", "PATCH"}:
                    # Try to send as JSON if parseable
                    try:
                        parsed = json.loads(body)
                        req_kwargs["json"] = parsed
                    except (json.JSONDecodeError, TypeError):
                        req_kwargs["content"] = body

                resp = await client.request(method, url, **req_kwargs)

            # Format response
            resp_headers = dict(resp.headers)
            body_text = resp.text
            truncated = len(body_text) > _MAX_BODY_CHARS
            if truncated:
                body_text = body_text[:_MAX_BODY_CHARS]

            result = {
                "status": resp.status_code,
                "headers": {k: v for k, v in resp_headers.items()
                            if k.lower() in ("content-type", "content-length", "location",
                                              "server", "x-request-id", "x-ratelimit-remaining")},
                "body": body_text,
                "truncated": truncated,
            }
            return json.dumps(result, indent=2, ensure_ascii=False)

        except httpx.ConnectError as e:
            return f"Error: Connection failed — {e}"
        except httpx.TimeoutException:
            return "Error: Request timed out (30s)"
        except Exception as e:
            return f"Error: {e}"
