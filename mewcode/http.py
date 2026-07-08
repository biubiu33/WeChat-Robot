from __future__ import annotations

import httpx


def create_http_client() -> httpx.Client:
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=30.0)
    return httpx.Client(timeout=timeout)
