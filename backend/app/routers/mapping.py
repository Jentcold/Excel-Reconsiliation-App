from __future__ import annotations

import io
from datetime import datetime, timezone

import pandas as pd
from appwrite.exception import AppwriteException
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from ..appwrite_client import Query, docs
from ..auth import CurrentUser, require_commercial, require_reports
from ..processing.loader import load_with_header
from ..schema import TBL_MAPPING
from .reports import refresh_quietly

router = APIRouter(prefix="/mapping", tags=["mapping"])

MAP_SHEET = "tblMapping data"

COLUMN_MAP = {
    "Unified_Code": "unified_code",
    "PSI_Model": "psi_model",
    "Inventory_Family": "inventory_family",
    "DSR_Item_Model": "dsr_item_model",
    "Comment": "comment",
}

FIELDS = tuple(COLUMN_MAP.values())


class MappingRow(BaseModel):
    unified_code: str = Field(min_length=1, max_length=128)
    psi_model: str | None = None
    inventory_family: str | None = None
    dsr_item_model: str | None = None
    comment: str | None = None


class MappingPatch(BaseModel):
    unified_code: str | None = None
    psi_model: str | None = None
    inventory_family: str | None = None
    dsr_item_model: str | None = None
    comment: str | None = None


def _serialise(doc: dict) -> dict:
    row = {"id": doc["$id"], "updated_by": doc.get("updated_by"),
           "updated_at": doc.get("updated_at")}
    row.update({f: doc.get(f) for f in FIELDS})
    return row


def _all_rows() -> list[dict]:
    return docs.rows(TBL_MAPPING, [Query.limit(5000)])


def _stamp(user: CurrentUser) -> dict:
    return {"updated_by": user.email, "updated_at": datetime.now(timezone.utc).isoformat()}


@router.get("")
async def list_mapping(user: CurrentUser = Depends(require_reports)):
    rows = [_serialise(d) for d in _all_rows()]
    rows.sort(key=lambda r: (r.get("unified_code") or "").lower())
    return {"rows": rows, "editable": user.role == "commercial"}


@router.post("/import")
async def import_mapping(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_commercial),
):
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That file is empty.")

    try:
        df = load_with_header(data, MAP_SHEET, ["Unified_Code", "PSI_Model"], source="Map")
    except ValueError:
        try:
            df = pd.read_excel(io.BytesIO(data))
            df.columns = [str(c).strip() for c in df.columns]
        except Exception:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "That file isn't a readable Excel workbook (.xlsx or .xls).",
            )

    missing = [c for c in ("Unified_Code",) if c not in df.columns]
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Mapping file is missing the {missing[0]} column.")

    existing = {(d.get("unified_code") or "").strip().lower(): d for d in _all_rows()}
    added = updated = skipped = 0

    for _, raw in df.iterrows():
        payload = {}
        for source, field in COLUMN_MAP.items():
            value = raw.get(source)
            payload[field] = None if pd.isna(value) else str(value).strip()
        code = (payload.get("unified_code") or "").strip()
        if not code or code.lower() == "nan":
            skipped += 1
            continue
        payload.update(_stamp(user))
        key = code.lower()
        try:
            if key in existing:
                docs.update(TBL_MAPPING, existing[key]["$id"], payload)
                updated += 1
            else:
                payload["active"] = True
                docs.create(TBL_MAPPING, payload)
                added += 1
        except AppwriteException:
            skipped += 1

    refresh_quietly()
    return {"message": f"{added} added, {updated} updated, {skipped} skipped.",
            "added": added, "updated": updated, "skipped": skipped}


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_row(body: MappingRow, user: CurrentUser = Depends(require_commercial)):
    code = body.unified_code.strip()
    clash = docs.rows(TBL_MAPPING, [Query.equal("unified_code", code), Query.limit(1)])
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{code} is already in the mapping table.")
    payload = body.model_dump()
    payload["unified_code"] = code
    payload["active"] = True
    payload.update(_stamp(user))
    row = _serialise(docs.create(TBL_MAPPING, payload))
    refresh_quietly()
    return {"row": row}


@router.patch("/{row_id}")
async def edit_row(row_id: str, body: MappingPatch,
                   user: CurrentUser = Depends(require_commercial)):
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if not payload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to change.")
    payload.update(_stamp(user))
    try:
        row = _serialise(docs.update(TBL_MAPPING, row_id, payload))
    except AppwriteException:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That mapping row no longer exists.")
    refresh_quietly()
    return {"row": row}


@router.delete("/{row_id}")
async def delete_row(row_id: str, user: CurrentUser = Depends(require_commercial)):
    try:
        docs.delete(TBL_MAPPING, row_id)
    except AppwriteException:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That mapping row no longer exists.")
    refresh_quietly()
    return {"message": "Row removed."}
