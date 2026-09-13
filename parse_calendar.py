import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

DOC_ID = "1v-tD11F1KC_pT0bZzgPMzhA_wcXRPu3R"
EXPORT_URL = f"https://docs.google.com/document/d/{DOC_ID}/export?format=html"

MONTH_MAP = {
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12, "january": 1, "february": 2,
    "march": 3, "april": 4, "may": 5
}

TIME_REGEX = r'(@?\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?(?:\s*[-–]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?|\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*until\s*pau)'

def fetch_html():
    res = requests.get(EXPORT_URL)
    if res.status_code != 200:
        raise Exception("Failed to fetch document.")
    return res.text

def parse_time(t_str, base_date):
    clean_t = t_str.lower().replace("@", "").strip()
    for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M"):
        try:
            pt = datetime.strptime(clean_t, fmt).time()
            return datetime.combine(base_date.date(), pt)
        except ValueError:
            continue
    return None

def parse_time_range(time_str, base_date):
    clean_str = time_str.lower().replace("@", "").strip()
    if "-" in clean_str or "–" in clean_str:
        parts = re.split(r'[-–]', clean_str)
        p1 = parse_time(parts[0], base_date)
        p2 = parse_time(parts[1], base_date)
        if p1 and p2:
            return p1, p2
    elif "until pau" in clean_str:
        p1 = parse_time(clean_str.replace("until pau", ""), base_date)
        if p1:
            return p1, p1 + timedelta(hours=3)
    else:
        p1 = parse_time(clean_str, base_date)
        if p1:
            return p1, p1 + timedelta(hours=2)
    return base_date + timedelta(hours=12), base_date + timedelta(hours=14)

def sanitize_summary(text):
    text = re.sub(r'\s+', ' ', text).strip()
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")

def process_cell_lines(lines, base_date):
    events = []
    curr_summary_parts = []
    curr_time_str = None

    def finalize_current():
        nonlocal curr_summary_parts, curr_time_str
        if not curr_summary_parts and not curr_time_str:
            return
        
        summary = sanitize_summary(" ".join(curr_summary_parts)) or "Band Event"

        if curr_time_str:
            s_dt, e_dt = parse_time_range(curr_time_str, base_date)
            events.append({"summary": summary, "start": s_dt, "end": e_dt, "all_day": False})
        else:
            events.append({"summary": summary, "start": base_date, "end": base_date + timedelta(days=1), "all_day": True})
        
        curr_summary_parts = []
        curr_time_str = None

    for line in lines[1:]:
        time_match = re.search(TIME_REGEX, line, re.IGNORECASE)
        if time_match:
            matched_time = time_match.group(0)
            line_text_remaining = line.replace(matched_time, "").strip()
            if curr_time_str:
                finalize_current()
            curr_time_str = matched_time
            if line_text_remaining:
                curr_summary_parts.append(line_text_remaining)
        else:
            if curr_time_str and line.startswith("@"):
                curr_summary_parts.append(line)
            else:
                if curr_time_str:
                    finalize_current()
                curr_summary_parts.append(line)

    finalize_current()
    return events

def extract_events(html):
    soup = BeautifulSoup(html, 'html.parser')
    events = []
    current_month = None
    current_year = None

    for el in soup.find('body').find_all(['p', 'h1', 'h2', 'h3', 'table', 'span']):
        text = el.get_text(separator=" ").strip().lower()
        if el.name != 'table':
            for m_name, m_num in MONTH_MAP.items():
                if m_name in text and len(text) < 30:
                    current_month = m_num
                    current_year = 2026 if m_num >= 6 else 2027
            continue
            
        if el.name == 'table' and current_month and current_year:
            for row in el.find_all('tr'):
                cells = row.find_all('td')
                if len(cells) < 7:
                    continue
                for cell in cells:
                    cell_text = cell.get_text(separator="\n").strip()
                    if not cell_text:
                        continue
                    lines = [line.strip() for line in cell_text.split('\n') if line.strip()]
                    match = re.match(r'^(\d{1,2})$', lines[0])
                    if match:
                        day_num = int(match.group(1))
                        try:
                            base_date = datetime(current_year, current_month, day_num)
                        except ValueError:
                            continue
                        events.extend(process_cell_lines(lines, base_date))
    return events

def create_ics(events, filename="calendar.ics"):
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Kamehameha Band//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Kamehameha Band Program",
        "X-WR-TIMEZONE:Pacific/Honolulu"
    ]
    
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    
    for idx, evt in enumerate(events):
        summary_slug = re.sub(r'[^a-zA-Z0-9]', '', evt['summary'].lower())[:15] or "event"
        
        if evt.get("all_day"):
            dt_s = evt["start"].strftime("%Y%m%d")
            dt_e = evt["end"].strftime("%Y%m%d")
            uid = f"band-{dt_s}-{summary_slug}-{idx}@kamehamehaband"

            ics_lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{timestamp}",
                f"DTSTART;VALUE=DATE:{dt_s}",
                f"DTEND;VALUE=DATE:{dt_e}",
                f"SUMMARY:{evt['summary']}",
                "END:VEVENT"
            ])
        else:
            # HST to UTC (+10 hours) conversion
            utc_start = evt["start"] + timedelta(hours=10)
            utc_end = evt["end"] + timedelta(hours=10)
            
            dt_s = utc_start.strftime("%Y%m%dT%H%M%SZ")
            dt_e = utc_end.strftime("%Y%m%dT%H%M%SZ")
            uid = f"band-{dt_s}-{summary_slug}-{idx}@kamehamehaband"

            ics_lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{timestamp}",
                f"DTSTART:{dt_s}",
                f"DTEND:{dt_e}",
                f"SUMMARY:{evt['summary']}",
                "END:VEVENT"
            ])
            
    ics_lines.append("END:VCALENDAR")
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\r\n".join(ics_lines))

if __name__ == "__main__":
    html_data = fetch_html()
    parsed_events = extract_events(html_data)
    create_ics(parsed_events)
