import re
import requests
from datetime import datetime, timedelta

DOC_ID = "1v-tD11F1KC_pT0bZzgPMzhA_wcXRPu3R"
EXPORT_URL = f"https://docs.google.com/document/d/{DOC_ID}/export?format=txt"

MONTH_MAP = {
    "june": 6, "iune": 6, "july": 7, "iulai": 7,
    "august": 8, "ʻaukake": 8, "aukake": 8,
    "september": 9, "kepakemapa": 9, "october": 10, "ʻokakopa": 10, "okakopa": 10,
    "november": 11, "novemapa": 11, "december": 12, "kēkēmapa": 12, "kekemapa": 12,
    "january": 1, "ianuali": 1, "february": 2, "pepeluali": 2,
    "march": 3, "malaki": 3, "april": 4, "ʻapelila": 4, "apelila": 4, "may": 5, "mei": 5
}

def fetch_text():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    res = requests.get(EXPORT_URL, headers=headers)
    if res.status_code != 200:
        raise Exception(f"Failed to fetch doc: HTTP {res.status_code}")
    return res.text

def parse_single_time(t_str, base_date):
    t_str = t_str.strip()
    for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M"):
        try:
            parsed_t = datetime.strptime(t_str, fmt).time()
            return datetime.combine(base_date.date(), parsed_t)
        except ValueError:
            continue
    return None

def parse_time_range(time_str, base_date):
    time_str = time_str.strip().lower().replace("@", "").strip()
    match = re.match(r'(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*-\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)', time_str)
    if match:
        start_raw, end_raw = match.groups()
        if not re.search(r'am|pm', start_raw) and re.search(r'am|pm', end_raw):
            start_raw += f" {re.search(r'am|pm', end_raw).group()}"
        s_dt = parse_single_time(start_raw, base_date)
        e_dt = parse_single_time(end_raw, base_date)
        if s_dt and e_dt:
            return s_dt, e_dt
        elif s_dt:
            return s_dt, s_dt + timedelta(hours=1)
    s_dt = parse_single_time(time_str, base_date)
    if s_dt:
        return s_dt, s_dt + timedelta(hours=1)
    return base_date, base_date + timedelta(hours=1)

def process_cell(cell_text, current_year, current_month, events):
    cell_text = cell_text.strip()
    if not cell_text:
        return

    # Match day number ONLY if it appears at the exact start of the cell
    day_match = re.match(r'^(\d{1,2})\b(.*)', cell_text, re.DOTALL)
    if not day_match:
        return

    day_num = int(day_match.group(1))
    content = day_match.group(2).strip()

    if day_num < 1 or day_num > 31 or not content:
        return

    try:
        event_date = datetime(current_year, current_month, day_num)
    except ValueError:
        return

    # Extract times and titles cleanly
    times_found = re.findall(r'(@?\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?(?:\s*-\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?)', content, re.IGNORECASE)
    title = re.sub(r'@?\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?(?:\s*-\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?', '', content, flags=re.IGNORECASE).strip()
    title = re.sub(r'\s+', ' ', title)

    if title and len(title) > 2:
        if times_found and len(times_found[0].strip()) > 2:
            s_dt, e_dt = parse_time_range(times_found[0], event_date)
        else:
            s_dt = event_date
            e_dt = event_date + timedelta(hours=1)
        events.append({"summary": title, "start": s_dt, "end": e_dt})

def extract_events(text):
    events = []
    current_year = 2026
    current_month = None

    for line in text.split('\n'):
        line_clean = line.strip()
        if not line_clean:
            continue

        month_found = False
        for m_name, m_num in MONTH_MAP.items():
            if m_name in line_clean.lower() and "calendar" in line_clean.lower():
                current_month = m_num
                current_year = 2027 if current_month < 6 else 2026
                month_found = True
                break
        if month_found:
            continue

        if current_month:
            # Split cells by table delimiters (| or tabs)
            if '|' in line_clean:
                cells = line_clean.split('|')
            elif '\t' in line_clean:
                cells = line_clean.split('\t')
            else:
                cells = [line_clean]

            for cell in cells:
                process_cell(cell, current_year, current_month, events)

    return events

def create_ics(events, filename="calendar.ics"):
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Kamehameha Band//EN",
        "CALSCALE:GREGORIAN",
        "X-WR-TIMEZONE:Pacific/Honolulu"
    ]
    for idx, evt in enumerate(events):
        dt_s = evt["start"].strftime("%Y%m%dT%H%M%S")
        dt_e = evt["end"].strftime("%Y%m%dT%H%M%S")
        ics_lines.extend([
            "BEGIN:VEVENT",
            f"UID:band-event-{idx}-{dt_s}@kamehamehaband",
            f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART;TZID=Pacific/Honolulu:{dt_s}",
            f"DTEND;TZID=Pacific/Honolulu:{dt_e}",
            f"SUMMARY:{evt['summary']}",
            "END:VEVENT"
        ])
    ics_lines.append("END:VCALENDAR")
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(ics_lines))

if __name__ == "__main__":
    text = fetch_text()
    events = extract_events(text)
    create_ics(events)
