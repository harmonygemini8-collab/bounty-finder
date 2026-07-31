"""Best-effort Algora bounty discovery.

Algora does not publish a stable, documented public bounty API. This source
targets the tRPC endpoint their web app uses and degrades gracefully (returns
an empty list) when the shape changes or access is blocked, so the rest of the
tool keeps working. GitHub remains the primary, reliable source.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.parse import quote

import requests

from ..models import Bounty
from ..parsing import best_amount

TRPC = "https://console.algora.io/api/trpc/bounty.list"


class AlgoraSource:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()

    def search(self, org: Optional[str] = None, limit: int = 50) -> list[Bounty]:
        payload: dict = {"json": {"status": "open", "limit": limit}}
        if org:
            payload["json"]["org"] = org
        try:
            resp = self.session.get(
                TRPC,
                params={"input": quote(json.dumps(payload))},
                timeout=30,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            return []

        items = self._extract_items(data)
        out: list[Bounty] = []
        for it in items:
            b = self._to_bounty(it)
            if b:
                out.append(b)
        return out

    @staticmethod
    def _extract_items(data) -> list:
        try:
            return data[0]["result"]["data"]["json"]["items"] or []
        except (KeyError, IndexError, TypeError):
            return []

    @staticmethod
    def _to_bounty(it: dict) -> Optional[Bounty]:
        try:
            repo = it.get("repo_full_name") or it.get("repository", {}).get("full_name", "?")
            number = it.get("number") or it.get("issue_number") or 0
            title = it.get("title", "")
            amount = it.get("amount")
            if isinstance(amount, dict):  # some payloads use {amount: cents}
                amount = amount.get("amount", 0) / 100.0
            amount = float(amount) if amount else best_amount(title)
            url = it.get("url") or it.get("html_url") or ""
            return Bounty(
                source="algora",
                repo=repo,
                number=int(number),
                title=title,
                url=url,
                amount_usd=amount,
            )
        except (TypeError, ValueError):
            return None
