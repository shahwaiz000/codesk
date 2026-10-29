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


def read_upload(filename: str, data: bytes, keep_unnamed: bool = False) -> pd.DataFrame:
    """keep_unnamed keeps columns without a heading, for sheets whose real heading is lower down."""
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
            sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=str, keep_default_na=False, engine="openpyxl")
            df = pick_data_sheet(sheets)
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
    if not keep_unnamed:
        df = df.loc[:, [not str(c).startswith("Unnamed") for c in df.columns]]
    df = df[~(df.astype(str).apply(lambda r: "".join(r).strip(), axis=1) == "")]  # drop fully empty rows
    return df.reset_index(drop=True)


def pick_data_sheet(sheets: dict) -> pd.DataFrame:
    """A workbook can hold a summary or pivot sheet next to the data. Use the sheet whose first row
    has the most real column names, which is the data (a pivot's first row is usually empty)."""
    def named(df) -> int:
        return sum(1 for c in df.columns if str(c).strip() and not str(c).startswith("Unnamed"))
    frames = list(sheets.values())
    if not frames:
        raise FileProblem("The Excel file has no sheets")
    return max(frames, key=named)  # max keeps the first sheet on a tie


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


def find_header(df: pd.DataFrame, aliases: tuple[str, ...], look: int = 10) -> tuple[pd.DataFrame, int]:
    """Some sheets have a title or a total line above the real heading. When the first row has none of
    the expected column names, look in the next few rows for one that does and use it as the heading.
    Returns the table and how many rows were above the heading (to keep row numbers right)."""
    if find_column(df, aliases):
        return df, 0
    for k in range(min(look, len(df))):
        values = list(df.iloc[k])
        if any(norm_header(v) in aliases for v in values):
            out = df.iloc[k + 1:].copy()
            out.columns = [str(v).strip() or f"Unnamed: {i}" for i, v in enumerate(values)]
            return out.reset_index(drop=True), k + 1
    return df, 0


MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def header_day(name, year: int) -> date | None:
    """A column heading that is a date, as in a sheet with one column per day: '27-Oct', '27/10/2026',
    or a real Excel date (read as '2026-10-27 00:00:00'). A heading without a year gets `year`."""
    text = str(name).strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?: 00:00:00)?", text)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[-/ ]([A-Za-z]{3})[A-Za-z]*", text)
    if m and m[2].lower() in MONTHS:
        try:
            return date(year, MONTHS[m[2].lower()], int(m[1]))
        except ValueError:
            return None
    if re.fullmatch(r"\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{1,2}[-/ ][A-Za-z]{3,9}[-/ ]\d{2,4}", text):
        return read_date(text)
    return None
