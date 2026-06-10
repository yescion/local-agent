"""Message serialization for SQLite storage."""

from __future__ import annotations

import json
import uuid
from typing import Any

from local_agent.storage.models import MessageRow, utcnow


def serialize_tool_calls(tool_calls: Any) -> list[dict]:
    if not tool_calls:
        return []
    result = []
    for tc in tool_calls:
        if hasattr(tc, "model_dump"):
            result.append(tc.model_dump())
        elif isinstance(tc, dict):
            result.append(tc)
        else:
            result.append(
                {
                    "id": getattr(tc, "id", str(uuid.uuid4())),
                    "type": "function",
                    "function": {
                        "name": getattr(getattr(tc, "function", tc), "name", ""),
                        "arguments": getattr(getattr(tc, "function", tc), "arguments", "{}"),
                    },
                }
            )
    return result


class MessageSerializer:
  @staticmethod
  def to_db(
      thread_id: str,
      message: dict[str, Any],
      msg_id: str | None = None,
      created_at: str | None = None,
  ) -> MessageRow:
      msg_id = msg_id or str(uuid.uuid4())
      tool_calls = message.get("tool_calls")
      return MessageRow(
          id=msg_id,
          thread_id=thread_id,
          role=message["role"],
          content=message.get("content"),
          thinking=message.get("thinking"),
          tool_calls=json.dumps(serialize_tool_calls(tool_calls), ensure_ascii=False)
          if tool_calls
          else None,
          tool_call_id=message.get("tool_call_id"),
          name=message.get("name"),
          ref_path=message.get("ref_path"),
          created_at=created_at or utcnow(),
      )

  @staticmethod
  def from_db(row: MessageRow) -> dict[str, Any]:
      msg: dict[str, Any] = {"role": row.role}
      if row.content is not None:
          msg["content"] = row.content
      if getattr(row, "thinking", None):
          msg["thinking"] = row.thinking
      if row.tool_calls:
          msg["tool_calls"] = json.loads(row.tool_calls)
      if row.tool_call_id is not None:
          msg["tool_call_id"] = row.tool_call_id
      if row.name:
          msg["name"] = row.name
      if row.ref_path:
          msg["ref_path"] = row.ref_path
      return msg

  @staticmethod
  def to_json_export(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
      exported = []
      for m in messages:
          m_copy = dict(m)
          if "tool_calls" in m_copy and m_copy["tool_calls"]:
              m_copy["tool_calls"] = serialize_tool_calls(m_copy["tool_calls"])
          exported.append(m_copy)
      return exported
