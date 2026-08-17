from __future__ import annotations

from datetime import date, datetime, timezone

from appwrite.exception import AppwriteException
from fastapi import APIRouter, Depends, File, HTTPException, Query as Q, UploadFile, status

from ..appwrite_client import Query, docs
from ..auth import CurrentUser, require_reports, require_roles
from ..periods import Period, PeriodParseError, parse_period
from ..processing.extract import extract
from ..schema import KINDS, MONTHLY_KINDS, ROLE_COMMERCIAL, TBL_UPLOADS
from ..store import DATA as DATA_KIND
from ..store import RAW as RAW_KIND
from ..store import put as store_put
from ..store import put_json as store_put_json
from ..store import remove as store_remove
from .reports import refresh_quietly

router = APIRouter(prefix="/uploads", tags=["uploads"])

require_upload = require_roles(ROLE_COMMERCIAL)

MAX_BYTES = 50 * 1024 * 1024


def _label(doc: dict) -> str:
    year, month = doc.get("period_year"), doc.get("period_month")
    if not year or not month:
        return doc.get("period_key") or ""
    return Period(year=year, month=month, day=doc.get("period_day")).label


def _serialise(doc: dict) -> dict:
    return {
        "id": doc["$id"],
        "kind": doc.get("kind"),
        "filename": doc.get("filename"),
        "period_key": doc.get("period_key"),
        "period_label": _label(doc),
        "year": doc.get("period_year"),
        "month": doc.get("period_month"),
        "day": doc.get("period_day"),
        "uploaded_by": doc.get("uploaded_by"),
        "uploaded_at": doc.get("uploaded_at"),
    }


def _psi_period(filename: str) -> Period:
    try:
        parsed = parse_period(filename)
    except PeriodParseError:
        parsed = None
    if parsed is not None and parsed.day is not None:
        return parsed
    today = date.today()
    return Period(year=today.year, month=today.month, day=today.day)


def _forget(doc: dict) -> None:
    store_remove(doc.get("file_id", ""))
    store_remove(doc.get("extract_file_id", ""))
    try:
        docs.delete(TBL_UPLOADS, doc["$id"])
    except AppwriteException:
        pass


def _existing(kind: str, period_key: str) -> dict | None:
    found = docs.rows(TBL_UPLOADS, [
        Query.equal("kind", kind), Query.equal("period_key", period_key), Query.limit(1),
    ])
    return found[0] if found else None


@router.get("")
async def list_uploads(
    kind: str | None = Q(default=None),
    user: CurrentUser = Depends(require_reports),
):
    queries = [Query.limit(200)]
    if kind:
        if kind not in KINDS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown kind \"{kind}\"")
        queries.append(Query.equal("kind", kind))
    rows = [_serialise(d) for d in docs.rows(TBL_UPLOADS, queries)]
    rows.sort(key=lambda r: r["period_key"], reverse=True)
    return {"uploads": rows}


@router.post("/{kind}", status_code=status.HTTP_201_CREATED)
async def upload(
    kind: str,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_upload),
):
    if kind not in KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown upload kind \"{kind}\"")

    filename = file.filename or ""
    if not filename.lower().endswith((".xlsx", ".xlsm", ".xls")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Please upload an Excel workbook.")

    monthly = kind in MONTHLY_KINDS
    if monthly:
        try:
            period = parse_period(filename)
        except PeriodParseError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    else:
        period = _psi_period(filename)

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That file is empty.")
    if len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "File is larger than the 50 MB limit.")

    period_key = period.month_key if monthly else period.day_key
    prior = _existing(kind, period_key)
    replaced = None

    if prior:
        prior_day = prior.get("period_day")
        if monthly and prior_day is not None and period.day is not None and prior_day > period.day:
            raise HTTPException(status.HTTP_409_CONFLICT, {
                "message": (
                    f"Not added. The {kind.upper()} on file for {period.month_label} already "
                    f"runs to day {prior_day}, which is newer than this file's day {period.day}."
                ),
                "kept": _serialise(prior),
            })
        replaced = _serialise(prior)

    try:
        columns = extract(kind, data, source=f"{kind.upper()} {period_key}")
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    except Exception as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Couldn't read that workbook: {e}")

    file_id = store_put(RAW_KIND, data, filename)
    extract_file_id = store_put_json(DATA_KIND, columns, f"{period_key}-{kind}.json")
    now = datetime.now(timezone.utc).isoformat()
    try:
        created = docs.create(TBL_UPLOADS, {
            "kind": kind,
            "file_id": file_id,
            "extract_file_id": extract_file_id,
            "filename": filename,
            "period_key": period_key,
            "period_year": period.year,
            "period_month": period.month,
            "period_day": period.day,
            "uploaded_by": user.email,
            "uploaded_at": now,
        })
    except AppwriteException as e:
        store_remove(file_id)
        store_remove(extract_file_id)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not record the upload: {e}")

    if prior:
        _forget(prior)

    refresh_quietly()

    verb = "replaced" if replaced else "added"
    return {
        "upload": _serialise(created),
        "replaced": replaced,
        "message": (
            f"{kind.upper()} for {period.label} {verb}."
            if monthly else f"PSI for {period.label} {verb}."
        ),
    }


@router.delete("/{upload_id}")
async def delete_upload(upload_id: str, user: CurrentUser = Depends(require_upload)):
    try:
        doc = docs.get(TBL_UPLOADS, upload_id)
    except AppwriteException:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That upload no longer exists.")
    _forget(doc)
    refresh_quietly()
    return {"message": f"Removed {doc.get('filename')}."}
