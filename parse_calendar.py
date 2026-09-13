import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

DOC_ID = "1v-tD11F1KC_pT0bZzgPMzhA_wcXRPu3R"
EXPORT_URL = f"https://docs.google.com/document/d/{DOC_ID}/export?format=html"

# Mapping for both English and Hawaiian month names to month integers
MONTH_MAP = {
    "june": 6, "juni": 6,
    "july": 7, "iulai": 7,
    "august": 8, "aukake": 8,
    "september": 9, "kepakemapa": 9,
    "october": 10, "okakopa": 10,
    "november": 11, "nowemapa": 11,
    "december": 12, "kekemapa": 12,
    "january": 1, "ianuali": 1,
    "february": 2, "pepeluali": 2,
    "march": 3, "malaki": 3,
    "april": 4, "apelila": 4,
    "may": 5, "mei": 5
}

# Strict regex requiring explicit am/pm, colons, or @ markers to prevent false matches on numbers like "Quarter 2"
TIME_PATTERNS = [
    r'(?:@\s*)?\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*[-–]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b',
    r'(?:@\s*)?\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b',
    r'(?:@\s*)?\b\d{1,2}:\d{2}\s*(?:am|pm)?\b'
]
STRICT_TIME_REGEX = re.compile(r'|'.join(TIME_PATTERNS), re.IGNORECASE)

def fetch_html(url=EXPORT_URL):
    response = requests.get(url)
    response.raise_for_status()
    return response.text

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
        
        p1 = parse_single_time(p1_str, base_date, force_pm=(p2_has_pm or not p1_has_pm))
        p2 = parse_single_time(p2_str, base_date, force_pm=(p1_has_pm or p2_has_pm))
        
        if p1 and p2:
            if p2 <= p1 and p2.hour < 12:
                p2 += timedelta(hours=12)
            return p1, p2
    else:
        p1 = parse_single_time(clean_str, base_date, force_pm=True)
        if p1:
            return p1, p1 + timedelta(hours=2)
            
    return base_date.replace(hour=12, minute=0), base_date.replace(hour=14, minute=0)

def sanitize_text(text):
    return re.sub(r'\s+', ' ', text).strip()

def process_cell(cell_elem, base_date):
    lines = [l.strip() for l in cell_elem.get_text(separator="\n").split("\n") if l.strip()]
    if not lines:
        return []
    
    day_match = re.match(r'^(\d{1,2})$', lines[0])
    if not day_match:
        return []
    
    day_num = int(day_match.group(1))
    try:
        event_date = base_date.replace(day=day_num)
    except ValueError:
        return []
    
    # Flatten multi-line text to fix line-wrapped times
    cell_body = " ".join(lines[1:])
    if not cell_body:
        return []

    events = []
    matches = list(STRICT_TIME_REGEX.finditer(cell_body))
    
    if not matches:
        events.append({
            "summary": sanitize_text(cell_body),
            "start": event_date.date(),
            "end": event_date.date(),
            "all_day": True
        })
        return events

    last_idx = 0
    for i, match in enumerate(matches):
        time_str = match.group(0)
        t_start, t_end = match.span()
        
        before_text = cell_body[last_idx:t_start].strip()
        next_start = matches[i+1].start() if i + 1 < len(matches) else len(cell_body)
        after_text = cell_body[t_end:next_start].strip()
        
        summary = before_text if before_text else after_text
        if before_text and after_text and i < len(matches) - 1:
            summary = f"{before_text} {after_text}"
            
        summary = sanitize_text(summary) or "Band Event"
        start_dt, end_dt = parse_time_range(time_str, event_date)
        
        events.append({
            "summary": summary,
            "start": start_dt,
            "end": end_dt,
            "all_day": False
        })
        last_idx = next_start

    return events

def extract_events(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    all_events = []
    
    tables = soup.find_all('table')
    for table in tables:
        # Traverse DOM backwards to extract month header text
        header_text = ""
        curr = table
        for _ in range(12):
            curr = curr.find_previous()
            if not curr:
                break
            header_text = curr.get_text(separator=" ") + " " + header_text
            if any(m in header_text.lower() for m in MONTH_MAP):
                break
        
        table_month = None
        for m_key, m_val in MONTH_MAP.items():
            if re.search(rf'\b{m_key}\b', header_text.lower()):
                table_month = m_val
                break
        
        if not table_month:
            continue

        # 2026-2027 Academic Year split
        table_year = 2026 if table_month >= 6 else 2027
        base_date = datetime(table_year, table_month, 1)

        for row in table.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            for cell in cells:
                cell_events = process_cell(cell, base_date)
                all_events.extend(cell_events)

    return all_events

if __name__ == "__main__":
    html = fetch_html()
    parsed_events = extract_events(html)
    print(f"Successfully extracted {len(parsed_events)} events across all months.")
