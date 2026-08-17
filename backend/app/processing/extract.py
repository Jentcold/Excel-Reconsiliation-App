from __future__ import annotations

import re
from typing import Any

import pandas as pd

from ..schema import KIND_DSR, KIND_INVENTORY, KIND_PSI
from .loader import load_with_header, normalize_full, split_date_columns

PSI_SHEET = "Disty"
DSR_SHEET = "Item Sales Summary"
INVENTORY_SHEETS = ("Honor Mob", "Honor PAD")

DSR_EXCLUDE_RE = re.compile(r"Gift|Compensation|Watch", re.IGNORECASE)

INVENTORY_COLS = ["Family", "Product Name", "RDP", "Volume", "Value", "WH-MAIN"]

VERSION = 1


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return df.where(pd.notna(df), None).to_dict(orient="records")


def extract_dsr(content: bytes, source: str = "DSR") -> dict[str, Any]:
    dsr = load_with_header(content, DSR_SHEET, ["Brand", "Item Model"], source=source)
    keep = [c for c in ("Brand", "Item Model", "Sum of Qty", "Sum of Net Sales") if c in dsr.columns]
    dsr = dsr[keep]
    dsr = dsr[~dsr["Item Model"].astype(str).str.contains(DSR_EXCLUDE_RE, na=False)]
    dsr["dsr_norm"] = dsr["Item Model"].apply(normalize_full)
    dsr = dsr.drop_duplicates(subset=["dsr_norm"], keep="first")
    return {"version": VERSION, "kind": KIND_DSR, "records": _records(dsr)}


def extract_psi(content: bytes) -> dict[str, Any]:
    psi = load_with_header(content, PSI_SHEET, ["Model", "Type"], source="PSI")
    psi = psi[psi["Type"] == "SO"]
    other_cols, date_cols = split_date_columns(psi)
    psi = psi[other_cols + date_cols]
    psi["unified_code_norm"] = psi["Internal Model"].apply(normalize_full)
    psi = psi.drop_duplicates(subset=["unified_code_norm"], keep="first")
    return {
        "version": VERSION,
        "kind": KIND_PSI,
        "records": _records(psi),
        "other_cols": [str(c) for c in other_cols],
        "date_cols": [str(c) for c in date_cols],
    }


def extract_inventory(content: bytes) -> dict[str, Any]:
    parts = []
    for sheet in INVENTORY_SHEETS:
        try:
            part = load_with_header(content, sheet, ["Product Name", "RDP"], source="Inventory")
        except ValueError:
            continue
        parts.append(part[[c for c in INVENTORY_COLS if c in part.columns]])
    if not parts:
        raise ValueError(
            "Inventory file has none of the expected sheets "
            f"({', '.join(INVENTORY_SHEETS)})."
        )
    inv = pd.concat(parts, ignore_index=True)
    inv["inv_norm"] = inv["Family"].apply(normalize_full)
    inv["prod_norm"] = inv["Product Name"].apply(normalize_full)
    return {"version": VERSION, "kind": KIND_INVENTORY, "records": _records(inv)}


_EXTRACTORS = {
    KIND_DSR: extract_dsr,
    KIND_PSI: lambda content, source="PSI": extract_psi(content),
    KIND_INVENTORY: lambda content, source="Inventory": extract_inventory(content),
}


def extract(kind: str, content: bytes, source: str = "") -> dict[str, Any]:
    extractor = _EXTRACTORS.get(kind)
    if extractor is None:
        raise ValueError(f"Nothing to extract for \"{kind}\".")
    return extractor(content, source or kind.upper())
