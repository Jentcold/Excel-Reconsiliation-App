from __future__ import annotations

import io

from appwrite.exception import AppwriteException
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from .. import cache
from ..appwrite_client import Query, docs
from ..auth import CurrentUser, require_reports
from ..periods import Period
from ..processing.export import build_workbook
from ..processing.extract import extract
from ..processing.pipeline import DsrInput, PipelineInput, run
from ..schema import KIND_DSR, KIND_INVENTORY, KIND_PSI, TBL_MAPPING, TBL_UPLOADS
from ..store import DATA as DATA_KIND
from ..store import get as store_get
from ..store import get_json
from ..store import put_json as store_put_json
from ..store import remove as store_remove

router = APIRouter(prefix="/reports", tags=["reports"])

DSR_MONTHS = 3


class NotReady(Exception):
    pass


def _uploads_by_kind() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in docs.rows(TBL_UPLOADS, [Query.limit(500)]):
        grouped.setdefault(row.get("kind", ""), []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda r: r.get("period_key", ""))
    return grouped


def _period_of(doc: dict) -> Period:
    return Period(
        year=doc.get("period_year") or 0,
        month=doc.get("period_month") or 1,
        day=doc.get("period_day"),
    )


def _extract_of(doc: dict) -> dict:
    file_id = doc.get("extract_file_id")
    if file_id:
        return get_json(file_id)

    kind, period_key = doc.get("kind", ""), doc.get("period_key", "")
    try:
        columns = extract(kind, store_get(doc["file_id"]), source=f"{kind.upper()} {period_key}")
    except (ValueError, AppwriteException) as e:
        raise NotReady(
            f"Couldn't read \"{doc.get('filename')}\" ({e}). Remove it or upload it again."
        )

    file_id = store_put_json(DATA_KIND, columns, f"{period_key}-{kind}.json")
    try:
        docs.update(TBL_UPLOADS, doc["$id"], {"extract_file_id": file_id})
    except AppwriteException:
        store_remove(file_id)
    return columns


def rebuild() -> dict:
    mapping = docs.rows(TBL_MAPPING, [Query.limit(5000)])
    if not mapping:
        raise NotReady("No product mapping yet — import the mapping file on the Mapping tab first.")

    uploads = _uploads_by_kind()
    dsr_docs = uploads.get(KIND_DSR, [])
    if not dsr_docs:
        raise NotReady("No DSR has been uploaded yet.")
    dsr_docs = dsr_docs[-DSR_MONTHS:]

    psi_docs = uploads.get(KIND_PSI, [])
    psi_doc = psi_docs[-1] if psi_docs else None
    inv_docs = uploads.get(KIND_INVENTORY, [])
    inv_doc = inv_docs[-1] if inv_docs else None

    try:
        payload = run(PipelineInput(
            mapping=mapping,
            dsrs=[DsrInput(period=_period_of(d),
                           data=_extract_of(d),
                           filename=d.get("filename", "")) for d in dsr_docs],
            psi=_extract_of(psi_doc) if psi_doc else None,
            psi_label=psi_doc.get("period_key", "") if psi_doc else "",
            inventory=_extract_of(inv_doc) if inv_doc else None,
        ))
    except AppwriteException as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Couldn't read a stored file: {e}")
    except ValueError as e:
        raise NotReady(str(e))

    rows = sum(len(s["rows"]) for s in payload["sheets"])
    return cache.put(payload, {
        "dsr": [d["file_id"] for d in dsr_docs],
        "psi": psi_doc["file_id"] if psi_doc else None,
        "inv": inv_doc["file_id"] if inv_doc else None,
    }, rows)


def refresh_quietly() -> None:
    try:
        rebuild()
    except NotReady:
        cache.clear()


def _payload() -> dict:
    payload = cache.current()
    if payload is not None:
        return payload
    try:
        return rebuild()
    except NotReady as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))


@router.get("/table")
async def table(user: CurrentUser = Depends(require_reports)):
    return _payload()


@router.get("/analytics")
async def analytics(user: CurrentUser = Depends(require_reports)):
    return _payload().get("analytics", {})


@router.get("/export")
async def export(user: CurrentUser = Depends(require_reports)):
    stream = io.BytesIO(build_workbook(_payload()["sheets"]))
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="combined_output.xlsx"'},
    )
