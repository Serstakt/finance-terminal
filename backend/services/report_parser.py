# -*- coding: utf-8 -*-
"""
Парсер финансовой отчетности.

Читает загруженные файлы (Excel / CSV / PDF / DOCX / HTML) и извлекает
МАКСИМАЛЬНО ВСЕ строки отчета, сохраняя исходные названия показателей —
по аналогии с таблицами на https://smart-lab.ru/q/MOEX/f/q/MSFO/ :
  Показатель | Период1 | Период2 | ...

Результат работы — «сырая таблица» (raw_table): список строк вида
{"name": "Выручка", "values": {"31.03.2025": 12345000, ...}}.

При наличии LLM_API_KEY строки дополнительно обогащаются LLM
(нормализация названий, определение периода отчета).
"""

import io
import json
import os
import re
from datetime import datetime

NUM_RE = re.compile(r"^-?\d[\d\s\u00a0\u202f.,-]*\d$|^-?\d$")


def _clean_cell(value) -> str:
    """Убираем переносы строк, лишние пробелы и маркеры вложенности."""
    if value is None:
        return ""
    s = str(value)
    s = s.replace("\u00a0", " ").replace("\u202f", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # срезаем нумерацию строк вида "1 " или "1.1 " в начале
    s = re.sub(r"^\d+(\.\d+)*\s+(?=[А-Яа-яA-Za-z(])", "", s)
    return s.strip()


def _to_number(text: str):
    """Пробует превратить ячейку в число ('1 234,5' -> 1234.5)."""

    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).replace("\u00a0", " ").replace("\u202f", " ").strip()
    if not s or s in ("-", "—", "–", "x", "нет"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    s = s.replace(" ", "").replace("\u2009", "")
    # приводим разделители: если есть и ',' и '.' — последний разделитель десятичный
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # одна запятая — скорее всего десятичная
        if re.fullmatch(r"-?\d+,\d{1,6}", s):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        val = float(s)
        return -val if neg else val
    except ValueError:
        return None


_DATE_RES = [
    (re.compile(r"(\d{1,2})[./](\d{1,2})[./](20\d{2})"),
     lambda m: f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"),
    (re.compile(r"(20\d{2})-(\d{1,2})-(\d{1,2})"),
     lambda m: f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"),
    (re.compile(r"(?i)Q([1-4])\s*[-_/]?\s*(20\d{2})"),
     lambda m: f"Q{m.group(1)} {m.group(2)}"),
    (re.compile(r"(?i)(20\d{2})\s*[-_/]?\s*Q([1-4])"),
     lambda m: f"Q{m.group(2)} {m.group(1)}"),
    (re.compile(r"(?i)(янв|фев|мар|апр|ма[йю]|июн|июл|авг|сен|окт|но|дек)[a-z]*\.?\s+(20\d{2})"),
     lambda m: f"{m.group(2)}-{m.group(1)[:3].capitalize()}"),
    (re.compile(r"^(20\d{2})(?:\s*(?:год|Год|FY))?$"),
     lambda m: m.group(1)),
]


def normalize_period_label(raw: str):
    """Возвращает нормализованную метку периода или None, если это не период."""
    s = _clean_cell(raw)
    if not s or len(s) > 40:
        return None
    for rx, fmt in _DATE_RES:
        m = rx.search(s)
        if m and len(s) <= 40:
            return fmt(m)
    return None


def _is_number_row_name(name: str) -> bool:
    return bool(re.fullmatch(r"\d+(\.\d+)*", name))


# ---------------------------------------------------------------------------
# Читатели файлов
# ---------------------------------------------------------------------------

def _rows_from_xlsx(content: bytes):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    rows = []
    for ws in wb.worksheets:
        sheet_rows = [[c.value for c in row] for row in ws.iter_rows()]
        if sheet_rows:
            rows.append((ws.title, sheet_rows))
    wb.close()
    return rows


def _rows_from_csv(content: bytes):
    text = _decode_text(content)
    delim = ";" if text.count(";") > text.count(",") else ","
    reader = __import__("csv").reader(io.StringIO(text), delimiter=delim)
    sheet = [[cell for cell in row] for row in reader]
    return [("csv", sheet)]


def _decode_text(content: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def _rows_from_pdf(content: bytes):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    sheet = []
    for page in reader.pages:
        for line in (page.extract_text() or "").splitlines():
            cells = re.split(r"\s{2,}|\t", line.strip())
            if any(c.strip() for c in cells):
                sheet.append(cells)
    return [("pdf", sheet)]


def _rows_from_docx(content: bytes):
    import docx
    doc = docx.Document(io.BytesIO(content))
    sheet = []
    for table in doc.tables:
        for row in table.rows:
            sheet.append([cell.text for cell in row.cells])
    for para in doc.paragraphs:
        if para.text.strip():
            sheet.append([para.text])
    return [("docx", sheet)]


def _rows_from_html(content: bytes):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(_decode_text(content), "lxml")
    sheet = []
    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if any(cells):
            sheet.append(cells)
    return [("html", sheet)]


def extract_rows(filename: str, content: bytes):
    """Определяет тип файла и возвращает [(sheet_title, rows)]."""
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext in ("xlsx", "xlsm", "xls"):
        try:
            return _rows_from_xlsx(content)
        except Exception:
            return _rows_from_xlsx_strict(content)
    if ext in ("csv", "txt"):
        return _rows_from_csv(content)
    if ext == "pdf":
        return _rows_from_pdf(content)
    if ext == "docx":
        return _rows_from_docx(content)
    if ext in ("htm", "html"):
        return _rows_from_html(content)
    # пытаемся угадать по содержимому
    if content[:4] == b"PK\x03\x04":  # zip -> xlsx/docx
        try:
            return _rows_from_xlsx(content)
        except Exception:
            return _rows_from_docx(content)
    if content[:5] == b"%PDF-":
        return _rows_from_pdf(content)
    return _rows_from_csv(content)


def _rows_from_xlsx_strict(content):
    raise RuntimeError("Не удалось прочитать Excel-файл")


# ---------------------------------------------------------------------------
# Построение сырой таблицы
# ---------------------------------------------------------------------------

MAX_LABEL_LEN = 180   # максимальная длина названия показателя
MIN_NAME_LEN = 3      # минимальная длина названия строки


def build_raw_table(sheets) -> dict:
    """
    Собирает все непустые строки отчета: название + числовые значения.
    Колонки-даты распознаются как подписи периодов.
    """
    columns = {}          # col_idx -> нормализованная метка периода
    rows_out = []
    seen_names = set()

    for title, sheet_rows in sheets:
        # сначала определяем колонки с датами по всему листу
        local_cols = {}
        for row in sheet_rows:
            for idx, cell in enumerate(row):
                label = normalize_period_label(cell)
                if label and idx not in local_cols:
                    local_cols[idx] = label
        for idx, label in local_cols.items():
            columns.setdefault(idx, label)

        for row in sheet_rows:
            cells = [_clean_cell(c) for c in row]
            if not any(cells):
                continue
            # находим первое содержательное текстовое значение (не число, не дату)
            name = ""
            name_idx = -1
            for idx, cell in enumerate(cells):
                if not cell or _is_number_row_name(cell):
                    continue
                if idx in local_cols or normalize_period_label(cell):
                    continue
                if _to_number(cell) is not None:
                    continue
                name = cell
                name_idx = idx
                break
            if not name or len(name) < MIN_NAME_LEN or len(name) > MAX_LABEL_LEN:
                continue
            # собираем числа справа от названия
            values = {}
            for idx in range(name_idx + 1, len(cells)):
                val = _to_number(cells[idx])
                if val is None:
                    continue
                key = columns.get(idx) or f"col_{idx}"
                if key not in values:
                    values[key] = val
            if not values:
                continue
            if name in seen_names:
                continue
            seen_names.add(name)
            rows_out.append({"name": name, "values": values})

    period_keys = sorted({k for r in rows_out for k in r["values"].keys()},
                         key=_period_sort_key, reverse=True)
    return {"columns": period_keys, "rows": rows_out}


def _period_sort_key(label: str):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", label)
    if m:
        return (int(m.group(1)) * 12 + int(m.group(2))) * 10
    m = re.match(r"^Q(\d)\s+(\d{4})$", label)
    if m:
        return int(m.group(2)) * 12 + int(m.group(1)) * 3
    m = re.match(r"^(\d{4})$", label)
    if m:
        return int(m.group(1)) * 12 + 12
    return 0


# ---------------------------------------------------------------------------
# LLM-обогащение (опционально)
# ---------------------------------------------------------------------------

LLM_PROMPT = """Ты — финансовый аналитик. Ниже строки финансовой отчетности компании {ticker}.
Верни JSON вида {{"period": "...", "period_type": "quarterly|annual", "end_date": "YYYY-MM-DD",
"rows": [{{"name": "каноническое название показателя на русском", "key": "snake_case_id"}}]}}.
Период определи по самой свежей дате в заголовках колонок: {columns}
Строки (название | значения):
{rows}
Ответь ТОЛЬКО валидным JSON без пояснений."""


async def llm_enrich(ticker: str, raw: dict) -> dict:
    """
    Если задан LLM_API_KEY (OpenAI-совместимый API), просим модель
    нормализовать названия и определить период отчета.
    Без ключа/при ошибке тихо возвращаем пустой dict — данные работают и так.
    """
    api_key = os.getenv("LLM_API_KEY")
    if not api_key or not raw.get("rows"):
        return {}
    try:
        import aiohttp
        base = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        lines = "\n".join(
            f"{r['name']} | " + "; ".join(f"{k}={v}" for k, v in list(r["values"].items())[:8])
            for r in raw["rows"][:200]
        )
        prompt = LLM_PROMPT.format(ticker=ticker, columns=", ".join(raw["columns"][:12]), rows=lines)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
            async with session.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={"model": model,
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0},
            ) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
                text = data["choices"][0]["message"]["content"]
                m = re.search(r"\{.*\}", text, re.S)
                return json.loads(m.group(0)) if m else {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

async def parse_report_file(filename: str, content: bytes, ticker: str) -> dict:
    """
    Полный разбор файла отчетности.
    Возвращает: {period, end_date, period_type, raw_table: {columns, rows}, llm}
    """
    sheets = extract_rows(filename, content)
    raw = build_raw_table(sheets)

    # Определяем период по самой свежей дате среди колонок
    period, end_date, period_type = guess_period(raw["columns"])

    llm = await llm_enrich(ticker, raw)
    if llm.get("period"):
        period = llm["period"]
    if llm.get("end_date"):
        end_date = llm["end_date"]
    if llm.get("period_type"):
        period_type = llm["period_type"]

    return {
        "period": period,
        "end_date": end_date,
        "period_type": period_type,
        "raw_table": raw,
        "llm": llm,
        "rows_count": len(raw["rows"]),
    }


def guess_period(columns):
    """По списку меток колонок определяет период самого свежего отчета."""
    dates = [c for c in columns if re.match(r"^\d{4}-\d{2}-\d{2}$", c)]
    quarters = [c for c in columns if re.match(r"^Q\d \d{4}$", c)]
    years = [c for c in columns if re.match(r"^\d{4}$", c)]

    if dates:
        latest = max(dates)
        y, mo, d = latest.split("-")
        q = (int(mo) - 1) // 3 + 1
        return f"Q{q} {y}", latest, "quarterly"
    if quarters:
        best = max(quarters, key=_period_sort_key)
        return best, "", "quarterly"
    if years:
        best = max(years)
        return best, f"{best}-12-31", "annual"

    now = datetime.now()
    q = (now.month - 1) // 3 + 1
    return f"Q{q} {now.year}", now.strftime("%Y-%m-%d"), "quarterly"
