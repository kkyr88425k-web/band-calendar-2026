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

def parse_single_time(t_str, base_date, force_pm=False):
    clean_t = t_str.lower().replace("@", "").strip()
    if force_pm and "am" not in clean_t and "pm" not in clean_t:
        clean_t += "pm"
        
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
        p1_str, p2_str = parts[0].strip(), parts[1].strip()
        
        p2_has_pm = "pm" in p2_str
        p1_has_pm = "pm" in p1_str
        
        # Inherit PM if time range implies evening (e.g., 5:30 - 7:30pm)
        p1 = parse_single_time(p1_str, base_date, force_pm=p2_has_pm)
        p2 = parse_single_time(p2_str, base_date, force_pm=p1_has_pm or p2_has_pm)
        
        if p1 and p2:
            if p2 <= p1:
                p2 += timedelta(hours=12)
            return p1, p2
            
    elif "until pau" in clean_str:
        p1 = parse_single_time(clean_str.replace("until pau", ""), base_date, force_pm=True)
        if p1:
            return p1, p1 + timedelta(hours=3)
    else:
        p1 = parse_single_time(clean_str, base_date, force_pm=True)
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
    
    tables = soup.find_all('table')
    for table in tables:
        # Detect month title from table text or immediate preceding elements
        table_text = table.get_text(separator=" ").lower()
        prev_text = ""
        prev_node = table.find_previous_sibling()
        if prev_node:
            prev_text = prev_node.get_text(separator=" ").lower()
            
        combined_context = prev_text + " " + table_text[:200]
        
        table_month = None
        table_year = None
        for m_name, m_num in MONTH_MAP.items():
            if m_name in combined_context:
                table_month = m_num
                table_year = 2026 if m_num >= 6 else 2027
                break
                
        if not table_month:
            continue

        for row in table.find_all('tr'):
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
                        base_date = datetime(table_year, table_month, day_num)
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
