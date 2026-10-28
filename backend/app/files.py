"""Reading uploaded CSV and Excel files into tables of text, with limits and plain-English errors.

Everything is read as text first. Amounts and dates are then read by the code that knows what
they mean, so nothing is silently guessed (Excel turning "007" into 7, or 1/2 into a date)."""
import io
import re
import zipfile
from datetime import date

import pandas as pd

MAX_BYTES = 5_000_000
MAX_ROWS = 20_000
MAX_UNZIPPED = 50_000_000


class FileProblem(Exception):
    """A problem with an uploaded file that the person can fix."""


def norm_header(name) -> str:
    """'Cash Received (SAR)' -> 'cashreceivedsar'."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def read_upload(filename: str, data: bytes) -> pd.DataFrame:
    if not data:
        raise FileProblem("The file is empty")
    if len(data) > MAX_BYTES:
        raise FileProblem(f"The file is larger than {MAX_BYTES // 1_000_000} MB")
    name = (filename or "").lower()
    try:
        if name.endswith(".xlsx"):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
                        raise FileProblem("This Excel file is too large when opened")
            except zipfile.BadZipFile:
                raise FileProblem("This is not a real .xlsx file. Save it again as Excel Workbook (.xlsx)")
            df = pd.read_excel(io.BytesIO(data), dtype=str, keep_default_na=False, engine="openpyxl")
        elif name.endswith(".csv"):
            text = None
            for enc in ("utf-8-sig", "cp1256", "latin-1"):  # Excel on Arabic Windows often saves CSV as cp1256
                try:
                    text = data.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, skipinitialspace=True)
        else:
            raise FileProblem("Upload a .csv or .xlsx file")
    except FileProblem:
        raise
    except Exception:
        raise FileProblem("The file could not be read. Check that it is a normal CSV or Excel file with one header row")
    if len(df) > MAX_ROWS:
        raise FileProblem(f"The file has more than {MAX_ROWS:,} rows")
    df = df.loc[:, [not str(c).startswith("Unnamed") for c in df.columns]]
    df = df[~(df.astype(str).apply(lambda r: "".join(r).strip(), axis=1) == "")]  # drop fully empty rows
    return df.reset_index(drop=True)


def find_column(df: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    by_norm = {norm_header(c): c for c in df.columns}
    for a in aliases:
        if a in by_norm:
            return by_norm[a]
    return None


def read_date(value) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.split(" ")[0] if re.match(r"^\d{4}-\d{2}-\d{2} ", text) else text
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", text):
        parsed = pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
    else:
        parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")  # 26/10/2026 is the local way
    return None if pd.isna(parsed) else parsed.date()


def clean_code(value) -> str:
    """A driver ID, order number or terminal ID as typed in a file: spaces trimmed, capitals,
    and the ".0" Excel adds to whole numbers removed (123456.0 -> 123456)."""
    text = " ".join(str(value if value is not None else "").split()).upper()
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".")[0]
    return text
