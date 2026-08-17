from __future__ import annotations

from typing import Any

from appwrite.client import Client
from appwrite.id import ID
from appwrite.query import Query
from appwrite.services.storage import Storage
from appwrite.services.users import Users

from .config import settings

try:
    from appwrite.services.tables_db import TablesDB as _DbService
    _ROW_API = True
except ImportError:
    from appwrite.services.databases import Databases as _DbService
    _ROW_API = False


def as_dict(result: Any) -> dict:
    if isinstance(result, dict):
        return result
    dump = getattr(result, "model_dump", None)
    if dump is None:
        return dict(result)
    out = dump(by_alias=True)
    inner = out.pop("data", None)
    if isinstance(inner, dict):
        out.update(inner)
    return out


def _server_client() -> Client:
    client = Client()
    client.set_endpoint(settings.appwrite_endpoint)
    client.set_project(settings.appwrite_project_id)
    client.set_key(settings.appwrite_api_key)
    return client


def admin_client() -> Client:
    return _server_client()


def session_client(secret: str) -> Client:
    client = Client()
    client.set_endpoint(settings.appwrite_endpoint)
    client.set_project(settings.appwrite_project_id)
    client.set_session(secret)
    return client


class Docs:
    def __init__(self, client: Client) -> None:
        self._svc = _DbService(client)
        self._db = settings.appwrite_database_id

    def create(self, table: str, data: dict[str, Any], doc_id: str | None = None) -> dict:
        doc_id = doc_id or ID.unique()
        if _ROW_API:
            return as_dict(self._svc.create_row(self._db, table, doc_id, data))
        return as_dict(self._svc.create_document(self._db, table, doc_id, data))

    def get(self, table: str, doc_id: str) -> dict:
        if _ROW_API:
            return as_dict(self._svc.get_row(self._db, table, doc_id))
        return as_dict(self._svc.get_document(self._db, table, doc_id))

    def list(self, table: str, queries: list[str] | None = None) -> Any:
        queries = queries or []
        if _ROW_API:
            return self._svc.list_rows(self._db, table, queries)
        return self._svc.list_documents(self._db, table, queries)

    def update(self, table: str, doc_id: str, data: dict[str, Any]) -> dict:
        if _ROW_API:
            return as_dict(self._svc.update_row(self._db, table, doc_id, data))
        return as_dict(self._svc.update_document(self._db, table, doc_id, data))

    def delete(self, table: str, doc_id: str) -> None:
        if _ROW_API:
            self._svc.delete_row(self._db, table, doc_id)
        else:
            self._svc.delete_document(self._db, table, doc_id)

    def rows(self, table: str, queries: list[str] | None = None) -> list[dict]:
        res = self.list(table, queries)
        if isinstance(res, dict):
            items = res.get("rows") or res.get("documents") or []
        else:
            items = getattr(res, "rows", None) or getattr(res, "documents", None) or []
        return [as_dict(r) for r in items]


_client = _server_client()
docs = Docs(_client)
storage = Storage(_client)
users = Users(_client)

__all__ = ["docs", "storage", "users", "admin_client", "session_client", "as_dict",
           "Docs", "ID", "Query"]
