from __future__ import annotations

import io
import re

import pandas as pd

DATE_COL_RE = re.compile(r"^\d{1,2}-[A-Za-z]{3}$|^\d{6,7}$")


class SheetNotFound(ValueError):
    pass


class HeaderNotFound(ValueError):
    pass


def load_with_header(
    content: bytes,
    sheet_name: str,
    key_columns: list[str],
    source: str = "workbook",
) -> pd.DataFrame:
    buf = io.BytesIO(content)
    try:
        raw = pd.read_excel(buf, sheet_name=sheet_name, header=None)
    except ValueError as e:
        raise SheetNotFound(f"{source}: sheet \"{sheet_name}\" not found ({e})") from e

    for i, row in raw.iterrows():
        cleaned = [str(v).strip() for v in row.values]
        if all(col in cleaned for col in key_columns):
            buf.seek(0)
            df = pd.read_excel(buf, sheet_name=sheet_name, header=i)
            df.columns = [str(c).strip() for c in df.columns]
            return df

    raise HeaderNotFound(
        f"{source}: couldn't find a header row containing {key_columns} "
        f"in sheet \"{sheet_name}\"."
    )


def sheet_names(content: bytes) -> list[str]:
    return pd.ExcelFile(io.BytesIO(content)).sheet_names


def normalize_full(name) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(name).lower()).strip()


def split_date_columns(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    date_cols = [c for c in df.columns if DATE_COL_RE.match(str(c))]
    other_cols = [c for c in df.columns if c not in date_cols]
    return other_cols, date_cols
