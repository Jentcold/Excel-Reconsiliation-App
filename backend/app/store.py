from __future__ import annotations

import json
from typing import Any

from appwrite.exception import AppwriteException
from appwrite.id import ID
from appwrite.input_file import InputFile

from .appwrite_client import as_dict, storage
from .config import settings

RAW = "raw"
DATA = "data"
IMAGE = "img"
CACHE = "cache"


def new_id(kind: str) -> str:
    return f"{kind}_{ID.unique()}"


def kind_of(file_id: str) -> str | None:
    prefix = (file_id or "").split("_", 1)[0]
    return prefix if prefix in (RAW, DATA, IMAGE, CACHE) else None


def put(kind: str, data: bytes, filename: str) -> str:
    result = storage.create_file(
        settings.bucket_id, new_id(kind), InputFile.from_bytes(data, filename)
    )
    return as_dict(result)["$id"]


def get(file_id: str) -> bytes:
    result = storage.get_file_download(settings.bucket_id, file_id)
    if isinstance(result, (dict, list)):
        return json.dumps(result).encode()
    return result


def put_json(kind: str, payload: Any, filename: str) -> str:
    return put(kind, json.dumps(payload, default=str).encode(), filename)


_JSON_MEMO_MAX = 12
_json_memo: dict[str, Any] = {}


def get_json(file_id: str) -> Any:
    if file_id in _json_memo:
        return _json_memo[file_id]
    value = json.loads(get(file_id))
    if len(_json_memo) >= _JSON_MEMO_MAX:
        del _json_memo[next(iter(_json_memo))]
    _json_memo[file_id] = value
    return value


def remove(file_id: str) -> None:
    if not file_id:
        return
    _json_memo.pop(file_id, None)
    try:
        storage.delete_file(settings.bucket_id, file_id)
    except AppwriteException:
        pass


def view_url(file_id: str, project_id: str, endpoint: str) -> str:
    return f"{endpoint}/storage/buckets/{settings.bucket_id}/files/{file_id}/view?project={project_id}"
