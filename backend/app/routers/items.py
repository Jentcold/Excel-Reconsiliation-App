from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone

import pandas as pd
from appwrite.exception import AppwriteException
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from ..appwrite_client import Query, docs
from ..auth import CurrentUser, require_commercial, require_items
from ..config import settings
from ..schema import TBL_ITEMS
from ..store import IMAGE as IMAGE_KIND
from ..store import put as store_put
from ..store import remove as store_remove
from ..store import view_url

router = APIRouter(prefix="/items", tags=["items"])

MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}

KNOWN = {
    "name": {"product name", "name", "item name", "model", "item model"},
    "category": {"category", "type", "segment"},
    "brand": {"brand", "manufacturer", "vendor"},
    "ram": {"ram", "memory"},
    "rom": {"rom", "storage", "capacity"},
    "rdp": {"rdp", "dealer price", "distributor price"},
    "rrp": {"rrp", "retail price", "recommended retail price", "price", "selling price"},
    "currency": {"currency", "ccy"},
    "unified_code": {"unified_code", "unified code", "code", "item code", "sku"},
}

UNNAMED_RE = re.compile(r"^(unnamed:?\s*\d*|nan|)$", re.IGNORECASE)


def _norm(value) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def _slug(*parts: str) -> str:
    joined = " ".join(_norm(p).lower() for p in parts if _norm(p) not in ("", "nan"))
    return re.sub(r"[^a-z0-9]+", "-", joined).strip("-")


def _price(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(re.sub(r"[,\s]", "", str(value)))
    except (TypeError, ValueError):
        return None


class Spec(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    value: str = Field(max_length=500)


class ItemBody(BaseModel):
    unified_code: str = Field(min_length=1, max_length=128)
    name: str | None = None
    brand: str | None = None
    category: str | None = None
    ram: str | None = None
    rom: str | None = None
    rdp: float | None = None
    rrp: float | None = None
    currency: str | None = "EGP"
    specs: list[Spec] = Field(default_factory=list)


class ItemPatch(BaseModel):
    name: str | None = None
    brand: str | None = None
    category: str | None = None
    ram: str | None = None
    rom: str | None = None
    rdp: float | None = None
    rrp: float | None = None
    currency: str | None = None
    specs: list[Spec] | None = None


def _serialise(doc: dict) -> dict:
    try:
        specs = json.loads(doc.get("specs_json") or "[]")
    except json.JSONDecodeError:
        specs = []
    image_id = doc.get("image_file_id")
    return {
        "id": doc["$id"],
        "unified_code": doc.get("unified_code"),
        "name": doc.get("name"),
        "brand": doc.get("brand"),
        "category": doc.get("category"),
        "ram": doc.get("ram"),
        "rom": doc.get("rom"),
        "rdp": doc.get("rdp"),
        "rrp": doc.get("rrp"),
        "currency": doc.get("currency") or "EGP",
        "specs": specs,
        "image_url": (
            view_url(image_id, settings.appwrite_project_id, settings.appwrite_endpoint)
            if image_id else None
        ),
        "updated_by": doc.get("updated_by"),
        "updated_at": doc.get("updated_at"),
    }


def _stamp(user: CurrentUser) -> dict:
    return {"updated_by": user.email, "updated_at": datetime.now(timezone.utc).isoformat()}


def _read_specs_sheet(data: bytes) -> pd.DataFrame:
    buf = io.BytesIO(data)
    try:
        raw = pd.read_excel(buf, sheet_name=0, header=None)
    except Exception:
        raise ValueError("That file isn't a readable Excel workbook (.xlsx or .xls).")
    for i, row in raw.iterrows():
        if any(_norm(v).lower() in KNOWN["name"] for v in row.values):
            buf.seek(0)
            df = pd.read_excel(buf, sheet_name=0, header=i)
            df.columns = [str(c).strip() for c in df.columns]
            return df
    raise ValueError('Couldn\'t find a header row with a "Product Name" column.')


def _field_for(header: str) -> str | None:
    key = str(header).strip().lower()
    for field, aliases in KNOWN.items():
        if key in aliases:
            return field
    return None


@router.get("")
async def list_items(user: CurrentUser = Depends(require_items)):
    rows = [_serialise(d) for d in docs.rows(TBL_ITEMS, [Query.limit(2000)])]
    rows.sort(key=lambda r: (r.get("brand") or "", r.get("name") or r.get("unified_code") or ""))
    return {"items": rows, "editable": user.role == "commercial"}


@router.post("/import")
async def import_items(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_commercial),
):
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That file is empty.")
    try:
        df = _read_specs_sheet(data)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    except Exception as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Couldn't read the sheet: {e}")

    df.columns = [str(c).strip() for c in df.columns]
    resolved = {c: _field_for(c) for c in df.columns}
    if "name" not in resolved.values():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No product-name column found. The sheet needs a \"Product Name\" column.",
        )

    for column, field in resolved.items():
        if field == "category":
            df[column] = df[column].ffill()

    existing = {(d.get("unified_code") or "").strip().lower(): d for d in docs.rows(TBL_ITEMS, [Query.limit(2000)])}
    added = updated = skipped = 0

    for _, raw in df.iterrows():
        payload: dict = {"currency": "EGP"}
        specs: list[dict] = []
        for column, field in resolved.items():
            value = raw.get(column)
            if value is None or pd.isna(value) or _norm(value) in ("", "nan"):
                continue
            if field in ("rdp", "rrp"):
                price = _price(value)
                if price is not None:
                    payload[field] = price
            elif field:
                payload[field] = _norm(value)
            elif not UNNAMED_RE.match(column.strip()):
                specs.append({"label": column, "value": _norm(value)})

        name = payload.get("name", "")
        if not name:
            skipped += 1
            continue

        code = payload.get("unified_code") or _slug(name, payload.get("ram", ""), payload.get("rom", ""))
        payload["unified_code"] = code
        payload.setdefault("brand", name.split()[0] if name.split() else None)
        payload["specs_json"] = json.dumps(specs)[:16000]
        payload.update(_stamp(user))

        try:
            key = code.lower()
            if key in existing:
                docs.update(TBL_ITEMS, existing[key]["$id"], payload)
                updated += 1
            else:
                docs.create(TBL_ITEMS, payload)
                added += 1
        except AppwriteException:
            skipped += 1

    return {"message": f"{added} added, {updated} updated, {skipped} skipped.",
            "added": added, "updated": updated, "skipped": skipped}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_item(body: ItemBody, user: CurrentUser = Depends(require_commercial)):
    code = body.unified_code.strip()
    if docs.rows(TBL_ITEMS, [Query.equal("unified_code", code), Query.limit(1)]):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{code} already has an item card.")
    payload = body.model_dump(exclude={"specs"})
    payload["unified_code"] = code
    payload["specs_json"] = json.dumps([s.model_dump() for s in body.specs])[:16000]
    payload.update(_stamp(user))
    return {"item": _serialise(docs.create(TBL_ITEMS, payload))}


@router.patch("/{item_id}")
async def update_item(item_id: str, body: ItemPatch,
                      user: CurrentUser = Depends(require_commercial)):
    payload = {k: v for k, v in body.model_dump(exclude={"specs"}).items() if v is not None}
    if body.specs is not None:
        payload["specs_json"] = json.dumps([s.model_dump() for s in body.specs])[:16000]
    if not payload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to change.")
    payload.update(_stamp(user))
    try:
        return {"item": _serialise(docs.update(TBL_ITEMS, item_id, payload))}
    except AppwriteException:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item no longer exists.")


@router.post("/{item_id}/image")
async def upload_image(item_id: str, file: UploadFile = File(...),
                       user: CurrentUser = Depends(require_commercial)):
    if file.content_type not in IMAGE_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use a PNG, JPEG or WebP image.")
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Image is over 10 MB.")

    try:
        item = docs.get(TBL_ITEMS, item_id)
    except AppwriteException:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item no longer exists.")

    file_id = store_put(IMAGE_KIND, data, file.filename or "item.png")
    updated = docs.update(TBL_ITEMS, item_id, {"image_file_id": file_id, **_stamp(user)})
    if item.get("image_file_id"):
        store_remove(item["image_file_id"])
    return {"item": _serialise(updated)}


@router.delete("/{item_id}")
async def delete_item(item_id: str, user: CurrentUser = Depends(require_commercial)):
    try:
        item = docs.get(TBL_ITEMS, item_id)
    except AppwriteException:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item no longer exists.")
    if item.get("image_file_id"):
        store_remove(item["image_file_id"])
    docs.delete(TBL_ITEMS, item_id)
    return {"message": "Item removed."}
