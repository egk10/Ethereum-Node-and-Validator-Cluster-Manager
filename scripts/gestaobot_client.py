"""Local bridge to the Integra Gestão process; never load Meta credentials."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class BotError(RuntimeError):
    pass


class Client:
    def __init__(self, base: str | None = None, timeout: int = 20):
        self.base = (base or os.environ.get("GESTAOBOT_URL") or
                     "http://127.0.0.1:8101").rstrip("/")
        url = urlsplit(self.base)
        if (url.scheme != "http" or url.hostname not in
                ("127.0.0.1", "localhost", "::1") or url.port != 8101 or
                url.username or url.password or url.path or url.query or url.fragment):
            raise BotError("GESTAOBOT_URL must be the local Gestão endpoint on port 8101")
        self.timeout = timeout

    def _request(self, path: str, payload: dict | None = None) -> dict:
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # Avoid response bodies: callers need the error, never credentials.
            raise BotError(f"Gestão bridge failed: {type(exc).__name__}") from exc
        if not isinstance(result, dict) or result.get("ok") is not True:
            reason = result.get("motivo", "request refused") if isinstance(result, dict) else "invalid JSON object"
            raise BotError(f"Gestão bridge refused: {str(reason)[:180]}")
        return result

    def alert(self, titulo: str, node: str, detalhe: str = "", approval: bool = False) -> dict:
        return self._request("/internal/cluster/alerta", {
            "titulo": titulo, "node": node, "detalhe": detalhe,
            "aprovacao": approval,
        })

    def approval(self, code: str) -> dict:
        if not re.fullmatch(r"[0-9]{6}", code):
            raise BotError("invalid approval code")
        return self._request(f"/internal/cluster/aprovacao/{code}")

    def conclude(self, code: str, ok: bool, text: str = "") -> dict:
        if not re.fullmatch(r"[0-9]{6}", code):
            raise BotError("invalid approval code")
        return self._request("/internal/cluster/conclusao", {
            "codigo": code, "ok": ok, "texto": text,
        })
