from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from appwrite.exception import AppwriteException

from .appwrite_client import Query, docs
from .schema import TBL_CACHE
from .store import CACHE as CACHE_KIND
from .store import get as store_get
from .store import put as store_put
from .store import remove as store_remove

CURRENT = "current"

_memo: dict[str, Any] | None = None
_entry_id: str | None = None
_file_id: str | None = None


def _entry() -> dict[str, Any] | None:
    global _entry_id
    rows = docs.rows(TBL_CACHE, [Query.equal("cache_key", CURRENT), Query.limit(1)])
    _entry_id = rows[0]["$id"] if rows else None
    return rows[0] if rows else None


def current() -> dict[str, Any] | None:
    global _memo, _file_id
    if _memo is not None:
        return _memo

    try:
        entry = _entry()
    except AppwriteException:
        return None
    if not entry:
        return None

    try:
        raw = store_get(entry["file_id"])
    except AppwriteException:
        _drop(entry)
        return None

    payload = json.loads(raw)
    payload["built_at"] = entry.get("created_at")
    _file_id, _memo = entry.get("file_id"), payload
    return payload


def put(payload: dict[str, Any], inputs: dict[str, Any], row_count: int) -> dict[str, Any]:
    global _memo

    built_at = datetime.now(timezone.utc).isoformat()
    payload["built_at"] = built_at
    file_id = store_put(CACHE_KIND, json.dumps(payload, default=str).encode(),
                        f"{CURRENT}.json")

    record = {
        "cache_key": CURRENT,
        "file_id": file_id,
        "inputs_json": json.dumps(inputs)[:4000],
        "row_count": row_count,
        "created_at": built_at,
    }

    global _entry_id, _file_id
    previous_file = _file_id
    try:
        if _entry_id is None:
            raise AppwriteException("no row known to this process")
        docs.update(TBL_CACHE, _entry_id, record)
    except AppwriteException:
        previous = _entry()
        previous_file = previous.get("file_id") if previous else None
        try:
            if previous:
                docs.update(TBL_CACHE, previous["$id"], record)
            else:
                _entry_id = docs.create(TBL_CACHE, record).get("$id")
        except AppwriteException:
            store_remove(file_id)
            raise

    if previous_file and previous_file != file_id:
        store_remove(previous_file)
    _file_id, _memo = file_id, payload
    return payload


def clear() -> None:
    entry = _entry()
    if entry:
        _drop(entry)
    else:
        _forget()


def _drop(entry: dict[str, Any]) -> None:
    _forget()
    store_remove(entry.get("file_id", ""))
    try:
        docs.delete(TBL_CACHE, entry["$id"])
    except AppwriteException:
        pass


def _forget() -> None:
    global _memo, _entry_id, _file_id
    _memo = _entry_id = _file_id = None
