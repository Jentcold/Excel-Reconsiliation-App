from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..periods import Period
from .extract import INVENTORY_COLS
from .loader import normalize_full


@dataclass
class DsrInput:
    period: Period
    data: dict[str, Any]
    filename: str = ""


@dataclass
class PipelineInput:
    mapping: list[dict[str, Any]]
    dsrs: list[DsrInput] = field(default_factory=list)
    psi: dict[str, Any] | None = None
    psi_label: str = ""
    inventory: dict[str, Any] | None = None


@dataclass
class Sheet:
    id: str
    name: str
    columns: list[dict[str, str]]
    rows: list[dict[str, Any]]
    totals: dict[str, float] = field(default_factory=dict)


def _col(key: str, label: str | None = None, type_: str = "text") -> dict[str, str]:
    return {"key": key, "label": label or key, "type": type_}


def _num(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[,\s]", "", str(value))
    if text in ("", "-", "nan", "None"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    return None if text in ("", "nan", "NaT", "None") else text


def _mapping_frame(mapping: list[dict[str, Any]]) -> pd.DataFrame:
    if not mapping:
        raise ValueError("No product mapping has been imported yet.")
    df = pd.DataFrame(mapping)
    for col in ("unified_code", "psi_model", "inventory_family", "dsr_item_model", "comment"):
        if col not in df.columns:
            df[col] = None
    df = df[df["unified_code"].notna()]
    df = df.drop_duplicates(subset=["unified_code"])
    df["unified_code_norm"] = df["unified_code"].apply(normalize_full)
    df["inv_norm"] = df["inventory_family"].apply(normalize_full)
    df["dsr_norm"] = df["dsr_item_model"].apply(normalize_full)
    return df.reset_index(drop=True)


def _frame(extract: dict[str, Any] | None, index: str | None = None) -> pd.DataFrame | None:
    if not extract:
        return None
    df = pd.DataFrame(extract.get("records") or [])
    if df.empty:
        return None
    if index:
        if index not in df.columns:
            return None
        df = df[df[index].notna()].set_index(index)
    return df


def _find_inventory_row(inv_family_norm: str, dsr_norm: str, inv: pd.DataFrame):
    match = inv[inv["inv_norm"] == inv_family_norm]
    if len(match) == 1:
        return match.iloc[0]
    if len(match) > 1:
        storage = re.search(r"(\d+)\s?gb", dsr_norm)
        if storage:
            narrowed = match[match["prod_norm"].str.contains(f"{storage.group(1)}gb", na=False)]
            if len(narrowed):
                return narrowed.iloc[0]
        return match.iloc[0]

    if inv_family_norm:
        tokens = inv_family_norm.split()
        if tokens:
            hits = inv[inv["prod_norm"].apply(lambda p: all(t in p for t in tokens))]
            if len(hits):
                return hits.iloc[0]
    return None


def run(inp: PipelineInput) -> dict[str, Any]:
    map_df = _mapping_frame(inp.mapping)

    dsrs = sorted(inp.dsrs, key=lambda d: (d.period.year, d.period.month))
    dsr_tables: list[tuple[DsrInput, pd.DataFrame | None]] = [
        (d, _frame(d.data, "dsr_norm")) for d in dsrs
    ]
    latest = dsr_tables[-1] if dsr_tables else None

    psi_df = psi_other = psi_dates = None
    if inp.psi:
        psi_df = _frame(inp.psi, "unified_code_norm")
        psi_other = inp.psi.get("other_cols") or []
        psi_dates = inp.psi.get("date_cols") or []

    inv_df = _frame(inp.inventory)

    diagnostics = {
        "mapping_rows": len(map_df),
        "dsr_months": [d.period.month_key for d in dsrs],
        "psi_label": inp.psi_label,
        "matched": {},
    }

    sheets = [
        _sheet_summary(map_df, latest, psi_df, psi_dates, inv_df, diagnostics),
        _sheet_dsr(map_df, dsr_tables, diagnostics),
        _sheet_psi(map_df, psi_df, psi_other, psi_dates, diagnostics),
    ]
    return {
        "sheets": [s.__dict__ for s in sheets],
        "diagnostics": diagnostics,
        "analytics": _analytics(sheets, dsrs),
    }


def _sheet_summary(map_df, latest, psi_df, psi_dates, inv_df, diagnostics) -> Sheet:
    dsr_input, dsr_df = latest if latest else (None, None)
    rows, inv_hits, dsr_hits, psi_hits = [], 0, 0, 0

    for _, m in map_df.iterrows():
        row: dict[str, Any] = {"unified_code": _clean(m["unified_code"])}

        if dsr_df is not None and m["dsr_norm"] in dsr_df.index:
            d = dsr_df.loc[m["dsr_norm"]]
            row["brand"] = _clean(d.get("Brand"))
            row["item_model"] = _clean(d.get("Item Model"))
            row["qty"] = _num(d.get("Sum of Qty"))
            row["net_sales"] = _num(d.get("Sum of Net Sales"))
            dsr_hits += 1
        else:
            row.update(brand=None, item_model=_clean(m["dsr_item_model"]), qty=None, net_sales=None)

        if inv_df is not None:
            inv_row = _find_inventory_row(m["inv_norm"], m["dsr_norm"], inv_df)
            if inv_row is not None:
                inv_hits += 1
                for col in INVENTORY_COLS:
                    row[col.lower().replace("-", "_").replace(" ", "_")] = (
                        _num(inv_row.get(col)) if col in ("RDP", "Volume", "Value", "WH-MAIN")
                        else _clean(inv_row.get(col))
                    )

        if psi_df is not None and m["unified_code_norm"] in psi_df.index:
            p = psi_df.loc[m["unified_code_norm"]]
            values = [v for v in (_num(p.get(c)) for c in (psi_dates or [])) if v is not None]
            row["psi_total"] = sum(values) if values else None
            row["psi_avg"] = round(sum(values) / len(values), 2) if values else None
            psi_hits += 1
        else:
            row["psi_total"] = row["psi_avg"] = None

        rows.append(row)

    diagnostics["matched"] = {
        "dsr": dsr_hits, "psi": psi_hits, "inventory": inv_hits, "of": len(map_df),
    }

    columns = [
        _col("unified_code", "Unified Code"),
        _col("brand", "Brand"),
        _col("item_model", "Item Model"),
        _col("qty", "Qty", "number"),
        _col("net_sales", "Net Sales", "number"),
        _col("product_name", "Product Name"),
        _col("rdp", "RDP", "number"),
        _col("volume", "Volume", "number"),
        _col("value", "Value", "number"),
        _col("wh_main", "WH-Main", "number"),
        _col("psi_total", "PSI Total", "number"),
        _col("psi_avg", "PSI Avg", "number"),
    ]
    name = "Summary"
    if dsr_input:
        name = f"Summary — {dsr_input.period.label}"
    return Sheet("summary", name, columns, rows, _totals(rows, columns))


def _sheet_dsr(map_df, dsr_tables, diagnostics) -> Sheet:
    columns = [_col("unified_code", "Unified Code"), _col("item_model", "Item Model"),
               _col("brand", "Brand")]
    for d, _ in dsr_tables:
        label = f"{calendar.month_abbr[d.period.month]} {d.period.year}"
        columns.append(_col(f"qty_{d.period.month_key}", f"{label} Qty", "number"))
        columns.append(_col(f"sales_{d.period.month_key}", f"{label} Net Sales", "number"))

    rows = []
    for _, m in map_df.iterrows():
        row: dict[str, Any] = {
            "unified_code": _clean(m["unified_code"]),
            "item_model": _clean(m["dsr_item_model"]),
            "brand": None,
        }
        for d, df in dsr_tables:
            key = d.period.month_key
            if df is not None and m["dsr_norm"] in df.index:
                rec = df.loc[m["dsr_norm"]]
                row["brand"] = row["brand"] or _clean(rec.get("Brand"))
                row[f"qty_{key}"] = _num(rec.get("Sum of Qty"))
                row[f"sales_{key}"] = _num(rec.get("Sum of Net Sales"))
            else:
                row[f"qty_{key}"] = row[f"sales_{key}"] = None
        rows.append(row)

    return Sheet("dsr", "DSR by month", columns, rows, _totals(rows, columns))


def _sheet_psi(map_df, psi_df, psi_other, psi_dates, diagnostics) -> Sheet:
    if psi_df is None:
        return Sheet("psi", "PSI", [_col("unified_code", "Unified Code")], [], {})

    skip = {"Type", "unified_code_norm"}
    detail_cols = [c for c in (psi_other or []) if c not in skip]

    columns = [_col("unified_code", "Unified Code"), _col("psi_model", "PSI Model")]
    columns += [_col(f"d_{i}", str(c)) for i, c in enumerate(detail_cols)]
    columns += [_col(f"p_{i}", str(c), "number") for i, c in enumerate(psi_dates or [])]
    columns += [_col("psi_total", "Total", "number"), _col("psi_avg", "Average", "number")]

    rows = []
    for _, m in map_df.iterrows():
        row: dict[str, Any] = {
            "unified_code": _clean(m["unified_code"]),
            "psi_model": _clean(m["psi_model"]),
        }
        if m["unified_code_norm"] in psi_df.index:
            p = psi_df.loc[m["unified_code_norm"]]
            for i, c in enumerate(detail_cols):
                row[f"d_{i}"] = _clean(p.get(c))
            values = []
            for i, c in enumerate(psi_dates or []):
                v = _num(p.get(c))
                row[f"p_{i}"] = v
                if v is not None:
                    values.append(v)
            row["psi_total"] = sum(values) if values else None
            row["psi_avg"] = round(sum(values) / len(values), 2) if values else None
        rows.append(row)

    return Sheet("psi", "PSI detail", columns, rows, _totals(rows, columns))


def _totals(rows: list[dict], columns: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for col in columns:
        if col["type"] != "number":
            continue
        values = [r.get(col["key"]) for r in rows]
        values = [v for v in values if isinstance(v, (int, float))]
        if values:
            totals[col["key"]] = round(sum(values), 2)
    return totals


def _analytics(sheets: list[Sheet], dsrs: list[DsrInput]) -> dict[str, Any]:
    summary = next(s for s in sheets if s.id == "summary")
    dsr_sheet = next(s for s in sheets if s.id == "dsr")

    by_month = []
    for d in sorted(dsrs, key=lambda x: (x.period.year, x.period.month)):
        key = d.period.month_key
        by_month.append({
            "period": key,
            "label": f"{calendar.month_abbr[d.period.month]} {d.period.year}",
            "qty": dsr_sheet.totals.get(f"qty_{key}", 0),
            "net_sales": dsr_sheet.totals.get(f"sales_{key}", 0),
        })

    top = sorted(
        (r for r in summary.rows if isinstance(r.get("net_sales"), (int, float))),
        key=lambda r: r["net_sales"], reverse=True,
    )[:10]

    return {
        "net_sales": summary.totals.get("net_sales", 0),
        "net_qty": summary.totals.get("qty", 0),
        "inventory_value": summary.totals.get("value", 0),
        "psi_total": summary.totals.get("psi_total", 0),
        "product_count": len(summary.rows),
        "by_month": by_month,
        "top_products": [
            {"label": r.get("item_model") or r.get("unified_code"),
             "net_sales": r.get("net_sales"), "qty": r.get("qty")}
            for r in top
        ],
    }
