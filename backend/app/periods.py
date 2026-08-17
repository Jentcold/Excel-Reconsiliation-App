from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

MONTH_NAMES = {name.lower(): num for num, name in enumerate(calendar.month_name) if name}
MONTH_ABBR = {name.lower(): num for num, name in enumerate(calendar.month_abbr) if name}


class PeriodParseError(ValueError):
    pass


@dataclass(frozen=True)
class Period:
    year: int
    month: int
    day: int | None = None

    @property
    def month_key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def day_key(self) -> str:
        if self.day is None:
            return self.month_key
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"

    @property
    def month_label(self) -> str:
        return f"{calendar.month_name[self.month]} {self.year}"

    @property
    def label(self) -> str:
        if self.day is None:
            return self.month_label
        return f"{calendar.month_abbr[self.month]} 1–{self.day}, {self.year}"

    def __str__(self) -> str:
        return self.day_key


def _month_from(token: str) -> int | None:
    token = token.strip().lower()
    if token.isdigit():
        num = int(token)
        return num if 1 <= num <= 12 else None
    for table in (MONTH_NAMES, MONTH_ABBR):
        if token in table:
            return table[token]
    for name, num in MONTH_NAMES.items():
        if token.startswith(name):
            return num
    return None


def infer_year(month: int, today: date | None = None) -> int:
    today = today or date.today()
    return today.year - 1 if month > today.month + 1 else today.year


def parse_period(filename: str, today: date | None = None) -> Period:
    stem = re.sub(r"\.(xlsx|xlsm|xls)$", "", filename, flags=re.IGNORECASE)
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", stem) if t]

    iso = re.search(r"(20\d{2})[^0-9]+(\d{1,2})[^0-9]+(\d{1,2})", stem)

    year = month = day = None
    named_month = False
    numeric: list[int] = []
    for tok in tokens:
        if tok.isdigit() and len(tok) == 4 and tok.startswith("20"):
            year = int(tok)
            continue
        as_month = _month_from(tok)
        if as_month is not None and not tok.isdigit():
            month = as_month
            named_month = True
            continue
        if tok.isdigit():
            numeric.append(int(tok))

    if month is None and numeric:
        month = numeric.pop(0) if 1 <= numeric[0] <= 12 else None
    stray_copy_suffix = named_month and year is None and len(numeric) == 1
    if numeric and not stray_copy_suffix:
        day = numeric[0]

    if (year is None or month is None or day is None) and iso:
        year, month, day = int(iso.group(1)), int(iso.group(2)), int(iso.group(3))

    if month is None:
        raise PeriodParseError(
            f"Couldn't read a month from \"{filename}\". "
            "Expected something like \"DSR - Mar\" or \"DSR - July\"."
        )
    if not 1 <= month <= 12:
        raise PeriodParseError(f"Month {month} in \"{filename}\" is not a real month.")

    if year is None:
        year = infer_year(month, today)

    if day is not None:
        last_day = calendar.monthrange(year, month)[1]
        if not 1 <= day <= last_day:
            raise PeriodParseError(
                f"Day {day} in \"{filename}\" isn't valid for "
                f"{calendar.month_name[month]} {year}."
            )
    return Period(year=year, month=month, day=day)
