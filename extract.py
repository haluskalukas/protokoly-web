import re
import pdfplumber
from datetime import date


def _parse_czech_date(s: str) -> date | None:
    s = re.sub(r'\s+', ' ', s.strip())
    parts = re.findall(r'\d+', s)
    if len(parts) == 3:
        try:
            return date(int(parts[2]), int(parts[1]), int(parts[0]))
        except ValueError:
            return None
    return None


def extract_from_pdf(stream) -> dict:
    with pdfplumber.open(stream) as pdf:
        text = pdf.pages[0].extract_text() or ''

    result = {}

    # Číslo protokolu: "č. PM-2026-168-a"
    m = re.search(r'č\.\s+(PM-[\d]+-[\d]+-[\w]+)', text)
    result['number'] = m.group(1) if m else None

    # Objednatel – jméno na stejném řádku, adresa na dalších řádcích
    m = re.search(r'Objednatel:\s*(.+)', text)
    if m:
        pos = m.end()
        name_line = m.group(1).strip()
        rest_lines = text[pos:].split('\n')
        addr_lines = []
        for line in rest_lines:
            line = line.strip()
            if not line:
                continue
            if re.match(r'^(Protokol|Datum|Místo|Měřil|Vyhotovil|www|Akulab|Strana)', line):
                break
            addr_lines.append(line)
            if len(addr_lines) == 2:   # max PSČ + město = 2 řádky adresy
                break
        parts = [name_line] + addr_lines
        result['client'] = ', '.join(p for p in parts if p)
    else:
        result['client'] = None

    # Datum měření
    m = re.search(r'Datum měření:\s*(\d+\.\s*\d+\.\s*\d+)', text)
    result['measurement_date'] = _parse_czech_date(m.group(1)) if m else None

    # Datum vydání: "V ... dne:  13. 7. 2026"
    m = re.search(r'dne:\s*(\d+\.\s*\d+\.\s*\d+)', text)
    result['issue_date'] = _parse_czech_date(m.group(1)) if m else None

    # Autorizační set
    m = re.search(r'Autorizační set\s+(G\d+)', text)
    result['auth_set'] = m.group(1) if m else None

    return result
