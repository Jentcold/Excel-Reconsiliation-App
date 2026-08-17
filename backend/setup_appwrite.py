from __future__ import annotations

import sys
import time

from appwrite.exception import AppwriteException
from appwrite.permission import Permission
from appwrite.role import Role

from app.appwrite_client import _client
from app.config import settings
from app.schema import TBL_CACHE, TBL_ITEMS, TBL_MAPPING, TBL_UPLOADS

try:
    from appwrite.services.tables_db import TablesDB as DbService
    ROW_API = True
except ImportError:
    from appwrite.services.databases import Databases as DbService
    ROW_API = False

from appwrite.services.storage import Storage

db = DbService(_client)
storage = Storage(_client)
DB_ID = settings.appwrite_database_id


def _call(row_name: str, doc_name: str, *args, **kwargs):
    fn = getattr(db, row_name, None) if ROW_API else None
    if fn is None:
        fn = getattr(db, doc_name)
    return fn(*args, **kwargs)


def exists(fn, *args) -> bool:
    try:
        fn(*args)
        return True
    except AppwriteException:
        return False


def ensure_database() -> None:
    if exists(db.get, DB_ID):
        print(f"  db {DB_ID}: exists")
        return
    db.create(DB_ID, "Excel Extraction Automation")
    print(f"  db {DB_ID}: created")


def ensure_table(table_id: str, name: str) -> None:
    getter = getattr(db, "get_table", None) if ROW_API else None
    getter = getter or db.get_collection
    if exists(getter, DB_ID, table_id):
        print(f"  table {table_id}: exists")
        return
    perms = [
        Permission.read(Role.users()),
        Permission.create(Role.users()),
        Permission.update(Role.users()),
        Permission.delete(Role.users()),
    ]
    _call("create_table", "create_collection", DB_ID, table_id, name, perms, False, True)
    print(f"  table {table_id}: created")


def add_string(table: str, key: str, size: int = 255, required: bool = False, array: bool = False) -> None:
    try:
        _call("create_string_column", "create_string_attribute",
              DB_ID, table, key, size, required, None, array)
        print(f"    +{key} (string)")
    except AppwriteException as e:
        if "already exists" not in str(e).lower():
            raise


def add_int(table: str, key: str, required: bool = False) -> None:
    try:
        _call("create_integer_column", "create_integer_attribute",
              DB_ID, table, key, required)
        print(f"    +{key} (int)")
    except AppwriteException as e:
        if "already exists" not in str(e).lower():
            raise


def add_float(table: str, key: str, required: bool = False) -> None:
    try:
        _call("create_float_column", "create_float_attribute",
              DB_ID, table, key, required)
        print(f"    +{key} (float)")
    except AppwriteException as e:
        if "already exists" not in str(e).lower():
            raise


def add_bool(table: str, key: str, default: bool | None = None) -> None:
    try:
        _call("create_boolean_column", "create_boolean_attribute",
              DB_ID, table, key, False, default)
        print(f"    +{key} (bool)")
    except AppwriteException as e:
        if "already exists" not in str(e).lower():
            raise


def add_index(table: str, key: str, attrs: list[str], itype: str = "key") -> None:
    try:
        _call("create_index", "create_index", DB_ID, table, key, itype, attrs)
        print(f"    ~{key} (index)")
    except AppwriteException as e:
        if "already exists" not in str(e).lower():
            raise


def ensure_bucket(bucket_id: str, name: str, max_mb: int, extensions: list[str]) -> None:
    if exists(storage.get_bucket, bucket_id):
        print(f"  bucket {bucket_id}: exists")
        return
    storage.create_bucket(
        bucket_id,
        name,
        [Permission.read(Role.users()), Permission.create(Role.users()),
         Permission.update(Role.users()), Permission.delete(Role.users())],
        False,
        True,
        max_mb * 1024 * 1024,
        extensions,
    )
    print(f"  bucket {bucket_id}: created")


def main() -> int:
    if not settings.appwrite_project_id or not settings.appwrite_api_key:
        print("ERROR: APPWRITE_PROJECT_ID and APPWRITE_API_KEY must be set in backend/.env")
        return 1

    print(f"Appwrite {settings.appwrite_endpoint} "
          f"({'TablesDB' if ROW_API else 'Databases'} API)\n")

    print("Database:")
    ensure_database()

    print("\nTables:")
    ensure_table(TBL_MAPPING, "Product mapping")
    ensure_table(TBL_UPLOADS, "Uploaded workbooks")
    ensure_table(TBL_ITEMS, "Item specs & prices")
    ensure_table(TBL_CACHE, "Processed output cache")

    time.sleep(1)

    print(f"\n  {TBL_MAPPING}:")
    add_string(TBL_MAPPING, "unified_code", 128, required=True)
    add_string(TBL_MAPPING, "psi_model", 255)
    add_string(TBL_MAPPING, "inventory_family", 255)
    add_string(TBL_MAPPING, "dsr_item_model", 255)
    add_string(TBL_MAPPING, "comment", 1000)
    add_bool(TBL_MAPPING, "active", default=True)
    add_string(TBL_MAPPING, "updated_by", 128)
    add_string(TBL_MAPPING, "updated_at", 64)
    add_index(TBL_MAPPING, "idx_unified_code", ["unified_code"], "unique")

    print(f"\n  {TBL_UPLOADS}:")
    add_string(TBL_UPLOADS, "kind", 32, required=True)
    add_string(TBL_UPLOADS, "file_id", 128, required=True)
    add_string(TBL_UPLOADS, "extract_file_id", 128)
    add_string(TBL_UPLOADS, "filename", 512)
    add_string(TBL_UPLOADS, "period_key", 32, required=True)
    add_int(TBL_UPLOADS, "period_year")
    add_int(TBL_UPLOADS, "period_month")
    add_int(TBL_UPLOADS, "period_day")
    add_string(TBL_UPLOADS, "uploaded_by", 128)
    add_string(TBL_UPLOADS, "uploaded_at", 64)
    add_index(TBL_UPLOADS, "idx_kind_period", ["kind", "period_key"])
    add_index(TBL_UPLOADS, "idx_kind", ["kind"])

    print(f"\n  {TBL_ITEMS}:")
    add_string(TBL_ITEMS, "unified_code", 128, required=True)
    add_string(TBL_ITEMS, "name", 255)
    add_string(TBL_ITEMS, "brand", 128)
    add_string(TBL_ITEMS, "category", 128)
    add_string(TBL_ITEMS, "ram", 32)
    add_string(TBL_ITEMS, "rom", 32)
    add_float(TBL_ITEMS, "rdp")
    add_float(TBL_ITEMS, "rrp")
    add_string(TBL_ITEMS, "currency", 16)
    add_string(TBL_ITEMS, "specs_json", 16384)
    add_string(TBL_ITEMS, "image_file_id", 128)
    add_string(TBL_ITEMS, "updated_by", 128)
    add_string(TBL_ITEMS, "updated_at", 64)
    add_index(TBL_ITEMS, "idx_item_code", ["unified_code"], "unique")

    print(f"\n  {TBL_CACHE}:")
    add_string(TBL_CACHE, "cache_key", 128, required=True)
    add_string(TBL_CACHE, "file_id", 128, required=True)
    add_string(TBL_CACHE, "inputs_json", 4096)
    add_int(TBL_CACHE, "row_count")
    add_string(TBL_CACHE, "created_at", 64)
    add_index(TBL_CACHE, "idx_cache_key", ["cache_key"], "unique")

    print("\nBucket:")
    ensure_bucket(settings.bucket_id, "Application files", 50,
                  ["xlsx", "xls", "xlsm", "png", "jpg", "jpeg", "webp", "json"])

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
