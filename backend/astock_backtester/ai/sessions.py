"""JSON-file session persistence under 运行产物/AI对话.

Sessions hold protocol messages (tool contents are digests only) plus display
turns for the frontend; full tool payloads stay in the in-memory
:class:`ToolResultStore` and are never persisted.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

SESSIONS_DIR_NAME = "AI对话"
MAX_PERSISTED_MESSAGES = 400
_SESSION_ID_RE = re.compile(r"[^A-Za-z0-9_-]")


def _safe_session_id(session_id: str) -> str | None:
    cleaned = _SESSION_ID_RE.sub("", str(session_id))
    return cleaned[:64] or None


class SessionStore:
    def __init__(self, ai_base_dir: str | Path) -> None:
        self._dir = Path(ai_base_dir) / SESSIONS_DIR_NAME

    @property
    def directory(self) -> Path:
        return self._dir

    def create(self, title: str = "新会话") -> dict:
        now = datetime.now(UTC).isoformat()
        session = {
            "session_id": uuid4().hex,
            "title": title[:40] or "新会话",
            "created_at": now,
            "updated_at": now,
            "rolling_summary": "",
            "pending_archive": [],
            "messages": [],
            "display": [],
        }
        self.save(session)
        return session

    def get(self, session_id: str) -> dict | None:
        safe = _safe_session_id(session_id)
        if safe is None:
            return None
        path = self._dir / f"{safe}.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def save(self, session: dict) -> None:
        safe = _safe_session_id(str(session.get("session_id", "")))
        if safe is None:
            raise ValueError("session_id 不合法")
        session["session_id"] = safe
        session["updated_at"] = datetime.now(UTC).isoformat()
        messages = session.get("messages") or []
        if len(messages) > MAX_PERSISTED_MESSAGES:
            session["messages"] = messages[-MAX_PERSISTED_MESSAGES:]
        display = session.get("display") or []
        if len(display) > MAX_PERSISTED_MESSAGES:
            session["display"] = display[-MAX_PERSISTED_MESSAGES:]
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{safe}.json"
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)

    def list_sessions(self) -> list[dict]:
        if not self._dir.exists():
            return []
        items: list[dict] = []
        for path in self._dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and payload.get("session_id"):
                items.append(
                    {
                        "session_id": payload.get("session_id"),
                        "title": payload.get("title", "新会话"),
                        "updated_at": payload.get("updated_at"),
                        "message_count": len(payload.get("display") or []),
                    }
                )
        items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return items

    def delete(self, session_id: str) -> bool:
        safe = _safe_session_id(session_id)
        if safe is None:
            return False
        path = self._dir / f"{safe}.json"
        if not path.exists():
            return False
        path.unlink()
        return True
