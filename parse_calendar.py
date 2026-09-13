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

def fetch_html():
    res = requests.get(EXPORT_URL)
    if res.status_code != 200:
        raise Exception("Failed to fetch doc.")
    return res.text

def parse_time(t_str, base_date):
    t_str = t_str.lower().replace("@", "").strip()
    for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M"):
        try:
            pt = datetime.strptime(t_str, fmt).time()
            return datetime.combine(base_date.date(), pt)
        except ValueError:
            continue
    return None

def extract_events(html):
    soup = BeautifulSoup(html, 'html.parser')
    events = []
    current_month = None
    current_year = None

    # Scan through document elements
    for el in soup.find('body').find_all(['p', 'h1', 'h2', 'h3', 'table', 'span']):
        text = el.get_text(separator=" ").strip().lower()
        
        # Detect Month context
        if el.name != 'table':
            for m_name, m_num in MONTH_MAP.items():
                if m_name in text and len(text) < 30:
                    current_month = m_num
                    # Fall months are 2026, Spring months are 2027
                    current_year = 2026 if m_num >= 6 else 2027
            continue
            
        # Parse Table if we have a known month
        if el.name == 'table' and current_month and current_year:
            for row in el.find_all('tr'):
                cells = row.find_all('td')
                if len(cells) < 7:
                    continue # Skip non-calendar rows
                    
                for cell in cells:
                    cell_text = cell.get_text(separator="\n").strip()
                    if not cell_text:
                        continue
                        
                    lines = [line.strip() for line in cell_text.split('\n') if line.strip()]
                    
                    # Check if cell starts with a day number
                    match = re.match(r'^(\d{1,2})$', lines[0])
                    if match:
                        day_num = int(match.group(1))
                        try:
                            base_date = datetime(current_year, current_month, day_num)
                        except ValueError:
                            continue
                            
                        # If there is event text after the day number
                        if len(lines) > 1:
                            event_text = " ".join(lines[1:])
                            
                            # Extract Time blocks
                            time_match = re.search(r'(@?\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?(?:\s*-\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?|\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*until\s*pau)', event_text, re.IGNORECASE)
                            
                            if time_match:
                                time_str = time_match.group(0)
                                summary = event_text.replace(time_str, "").strip()
                                summary = re.sub(r'\s+', ' ', summary)
                                
                                # Simple fallback time parsing
                                s_dt = base_date + timedelta(hours=12)
                                e_dt = base_date + timedelta(hours=14)
                                
                                if "-" in time_str:
                                    parts = time_str.split("-")
                                    p1 = parse_time(parts[0], base_date)
                                    p2 = parse_time(parts[1], base_date)
                                    if p1 and p2:
                                        s_dt, e_dt = p1, p2
                                elif "until pau" in time_str.lower():
                                    p1 = parse_time(time_str.replace("until pau", ""), base_date)
                                    if p1:
                                        s_dt = p1
                                        e_dt = p1 + timedelta(hours=3)
                                else:
                                    p1 = parse_time(time_str, base_date)
                                    if p1:
                                        s_dt = p1
                                        e_dt = p1 + timedelta(hours=2)
                                        
                                events.append({"summary": summary or "Band Event", "start": s_dt, "end": e_dt, "all_day": False})
                            else:
                                # All-day event
                                events.append({"summary": event_text, "start": base_date, "end": base_date + timedelta(days=1), "all_day": True})

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
        summary_slug = re.sub(r'[^a-zA-Z0-9]', '', evt['summary'].lower())[:25] or "event"
        
        if evt.get("all_day"):
            dt_s = evt["start"].strftime("%Y%m%d")
            dt_e = evt["end"].strftime("%Y%m%d")
            uid = f"band-{dt_s}-{summary_slug}@kamehamehaband"
            
            while uid in seen_uids:
                uid += "-1"
            seen_uids.add(uid)

            ics_lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}",
                f"DTSTART;VALUE=DATE:{dt_s}",
                f"DTEND;VALUE=DATE:{dt_e}",
                f"SUMMARY:{evt['summary']}",
                "END:VEVENT"
            ])
        else:
            dt_s = evt["start"].strftime("%Y%m%dT%H%M%S")
            dt_e = evt["end"].strftime("%Y%m%dT%H%M%S")
            uid = f"band-{dt_s}-{summary_slug}@kamehamehaband"
            
            while uid in seen_uids:
                uid += "-1"
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
        f.write("\r\n".join(ics_lines))

if __name__ == "__main__":
    html_data = fetch_html()
    parsed_events = extract_events(html_data)
    create_ics(parsed_events)
