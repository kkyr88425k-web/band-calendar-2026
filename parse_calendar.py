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
EVENT_KEYWORDS = {"rehearsal", "camp", "game", "vs", "concert", "workshop", "parade", "audition", "line", "guard", "drumline", "marching"}

def fetch_text():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    res = requests.get(EXPORT_URL, headers=headers)
    if res.status_code != 200:
        raise Exception(f"Failed to fetch doc: HTTP {res.status_code}")
    return res.text

def detect_month_and_year(line_clean):
    lower_line = line_clean.lower()
    
    if any(kw in lower_line for kw in EVENT_KEYWORDS):
        return None, None
        
    for m_name, m_num in MONTH_MAP.items():
        pattern = r'\b' + re.escape(m_name) + r'\b'
        if re.search(pattern, lower_line):
            year_match = re.search(r'\b(202[5-9])\b', lower_line)
            has_calendar = "calendar" in lower_line
            
            if year_match or has_calendar:
                if year_match:
                    year = int(year_match.group(1))
                else:
                    year = 2027 if m_num < 6 else 2026
                return m_num, year

    return None, None

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
        
        has_valid_time = False
        if time_match:
            t_str = time_match.group(0).strip()
            if re.search(r'am|pm|until', t_str, re.IGNORECASE) or '-' in t_str or ':' in t_str:
                has_valid_time = True

        if has_valid_time:
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

    has_table_delimiters = '\t' in text or '|' in text

    if has_table_delimiters:
        week_days = [None] * 7
        week_buffers = [[] for _ in range(7)]

        def flush_week():
            nonlocal events, week_days, week_buffers, current_year, current_month
            if not current_month or not current_year:
                return
            for col_idx in range(7):
                day_num = week_days[col_idx]
                lines = week_buffers[col_idx]
                if day_num and lines:
                    evs = parse_day_block(day_num, current_year, current_month, lines)
                    events.extend(evs)
            week_days = [None] * 7
            week_buffers = [[] for _ in range(7)]

        for line in text.split('\n'):
            line_raw = line
            line_clean = line.strip()
            if not line_clean:
                continue

            m_num, year = detect_month_and_year(line_clean)
            if m_num:
                flush_week()
                current_month = m_num
                current_year = year
                continue

            if not current_month:
                continue

            if any(day_name in line_clean.lower() for day_name in DAYS_OF_WEEK) and len(line_clean) > 15:
                continue

            cells = line_raw.split('\t') if '\t' in line_raw else line_raw.split('|')

            row_day_matches = []
            for cell in cells:
                cell_str = cell.strip()
                m = re.match(r'^\s*([1-9]|[12]\d|3[01])(?!\s*[:\d]|am|pm|a\.m|p\.m)\b\s*(.*)$', cell_str, re.IGNORECASE)
                row_day_matches.append(m)

            if any(m is not None for m in row_day_matches):
                flush_week()
                for col_idx, cell in enumerate(cells):
                    if col_idx >= 7:
                        break
                    m = row_day_matches[col_idx]
                    if m:
                        day_num = int(m.group(1))
                        remainder = m.group(2).strip()
                        week_days[col_idx] = day_num
                        if remainder:
                            week_buffers[col_idx].append(remainder)
            else:
                for col_idx, cell in enumerate(cells):
                    if col_idx >= 7:
                        break
                    cell_str = cell.strip()
                    if cell_str and week_days[col_idx] is not None:
                        week_buffers[col_idx].append(cell_str)

        flush_week()
    else:
        current_day = None
        day_lines = []

        def flush_day():
            nonlocal events, current_day, current_year, current_month, day_lines
            if current_day and current_month and current_year and day_lines:
                evs = parse_day_block(current_day, current_year, current_month, day_lines)
                events.extend(evs)
            day_lines = []

        for line in text.split('\n'):
            line_clean = line.strip()
            if not line_clean:
                continue

            m_num, year = detect_month_and_year(line_clean)
            if m_num:
                flush_day()
                current_month = m_num
                current_year = year
                current_day = None
                continue

            if not current_month:
                continue

            m = re.match(r'^\s*([1-9]|[12]\d|3[01])(?!\s*[:\d]|am|pm|a\.m|p\.m)\b\s*(.*)$', line_clean, re.IGNORECASE)
            if m:
                flush_day()
                current_day = int(m.group(1))
                remainder = m.group(2).strip()
                if remainder:
                    day_lines.append(remainder)
            elif current_day is not None:
                day_lines.append(line_clean)

        flush_day()

    return events

def create_ics(events, filename="calendar.ics"):
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Kamehameha Band//EN",
        "CALSCALE:GREGORIAN",
        "X-WR-TIMEZONE:Pacific/Honolulu"
    ]
    seen_uids = set()
    for evt in events:
        summary_slug = re.sub(r'[^a-zA-Z0-9]', '', evt['summary'].lower())[:30]
        if evt.get("all_day"):
            dt_s = evt["start"].strftime("%Y%m%d")
            dt_e = evt["end"].strftime("%Y%m%d")
            uid = f"band-{dt_s}-{summary_slug}@kamehamehaband"
            dedup_counter = 1
            base_uid = uid
            while uid in seen_uids:
                uid = f"{base_uid}-{dedup_counter}"
                dedup_counter += 1
            seen_uids.add(uid)

            ics_lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}",
                f"VALUE=DATE;DTSTART:{dt_s}",
                f"VALUE=DATE;DTEND:{dt_e}",
                f"SUMMARY:{evt['summary']}",
                "END:VEVENT"
            ])
        else:
            dt_s = evt["start"].strftime("%Y%m%dT%H%M%S")
            dt_e = evt["end"].strftime("%Y%m%dT%H%M%S")
            uid = f"band-{dt_s}-{summary_slug}@kamehamehaband"
            dedup_counter = 1
            base_uid = uid
            while uid in seen_uids:
                uid = f"{base_uid}-{dedup_counter}"
                dedup_counter += 1
            seen_uids.add(uid)

            ics_lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
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
