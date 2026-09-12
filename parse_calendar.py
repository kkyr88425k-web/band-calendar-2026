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

DAYS_OF_WEEK = {"sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"}

def fetch_text():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    res = requests.get(EXPORT_URL, headers=headers)
    if res.status_code != 200:
        raise Exception(f"Failed to fetch doc: HTTP {res.status_code}")
    return res.text

def parse_single_time(t_str, base_date):
    t_str = t_str.strip().lower().replace("@", "")
    for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M"):
        try:
            parsed_t = datetime.strptime(t_str, fmt).time()
            return datetime.combine(base_date.date(), parsed_t)
        except ValueError:
            continue
    return None

def parse_time_range(time_str, base_date):
    time_str = time_str.strip().lower().replace("@", "").strip()
    if "until pau" in time_str:
        s_part = time_str.replace("until pau", "").strip()
        s_dt = parse_single_time(s_part, base_date)
        if s_dt:
            return s_dt, s_dt + timedelta(hours=3)
    
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
            return s_dt, s_dt + timedelta(hours=2)

    s_dt = parse_single_time(time_str, base_date)
    if s_dt:
        return s_dt, s_dt + timedelta(hours=2)
    return None, None

def parse_day_block(day_num, year, month, lines):
    events = []
    if not lines:
        return events
    
    try:
        base_date = datetime(year, month, day_num)
    except ValueError:
        return events

    current_title = []
    
    for line in lines:
        line_clean = line.strip()
        if not line_clean or line_clean.lower() in DAYS_OF_WEEK:
            continue

        time_match = re.search(r'(@?\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?(?:\s*-\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?|\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*until\s*pau)', line_clean, re.IGNORECASE)
        
        if time_match and len(time_match.group(0).strip()) > 2:
            time_str = time_match.group(0)
            line_title = re.sub(re.escape(time_str), '', line_clean, flags=re.IGNORECASE).strip()
            line_title = re.sub(r'\s+', ' ', line_title)
            
            if line_title:
                current_title.append(line_title)
            
            full_title = " ".join(current_title).strip() if current_title else "Band Event"
            s_dt, e_dt = parse_time_range(time_str, base_date)
            if not s_dt:
                s_dt = base_date
                e_dt = base_date + timedelta(hours=1)
            
            events.append({"summary": full_title, "start": s_dt, "end": e_dt, "all_day": False})
            current_title = []
        else:
            current_title.append(line_clean)
            
    if current_title:
        full_title = " ".join(current_title).strip()
        if full_title and len(full_title) > 2:
            events.append({"summary": full_title, "start": base_date, "end": base_date + timedelta(days=1), "all_day": True})

    return events

def extract_events(text):
    events = []
    current_year = 2026
    current_month = None
    current_day = None
    day_lines = []

    def flush_current_day():
        nonlocal events, current_day, current_year, current_month, day_lines
        if current_day and current_month and current_year:
            evs = parse_day_block(current_day, current_year, current_month, day_lines)
            events.extend(evs)
        day_lines = []

    for line in text.split('\n'):
        line_clean = line.strip()
        if not line_clean:
            continue

        month_found = False
        for m_name, m_num in MONTH_MAP.items():
            if m_name in line_clean.lower() and ("calendar" in line_clean.lower() or len(line_clean) < 25):
                flush_current_day()
                current_month = m_num
                current_year = 2027 if current_month < 6 else 2026
                current_day = None
                month_found = True
                break
        if month_found:
            continue

        if current_month:
            day_match = re.match(r'^\s*([1-9]|[12]\d|3[01])(?!\s*[:\d]|am|pm|a\.m|p\.m)\b\s*(.*)$', line_clean, re.IGNORECASE)
            if day_match:
                flush_current_day()
                current_day = int(day_match.group(1))
                remainder = day_match.group(2).strip()
                if remainder:
                    day_lines.append(remainder)
            elif current_day is not None:
                day_lines.append(line_clean)

    flush_current_day()
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
        if evt.get("all_day"):
            dt_s = evt["start"].strftime("%Y%m%d")
            dt_e = evt["end"].strftime("%Y%m%d")
            ics_lines.extend([
                "BEGIN:VEVENT",
                f"UID:band-event-{idx}-{dt_s}@kamehamehaband",
                f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}",
                f"VALUE=DATE;DTSTART:{dt_s}",
                f"VALUE=DATE;DTEND:{dt_e}",
                f"SUMMARY:{evt['summary']}",
                "END:VEVENT"
            ])
        else:
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
