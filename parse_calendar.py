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

# Strictly require explicit time formats (colon or am/pm) to avoid matching "Quarter 2"
STRICT_TIME_REGEX = r'(\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b(?:\s*[-–]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?|\s*until\s*pau)?|\b\d{1,2}:\d{2}\b(?:\s*[-–]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?)'

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
        
        p1 = parse_single_time(p1_str, base_date, force_pm=(p2_has_pm or not p1_has_pm))
        p2 = parse_single_time(p2_str, base_date, force_pm=(p1_has_pm or p2_has_pm))
        
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

def process_cell(cell_text, base_date):
    # Collapse wrapped lines within the cell into unified text
    lines = [l.strip() for l in cell_text.split('\n') if l.strip()]
    if not lines or not re.match(r'^\d{1,2}$', lines[0]):
        return []

    events = []
    full_text = " ".join(lines[1:])
    
    # Split multiple events inside a single cell by time headers
    matches = list(re.finditer(STRICT_TIME_REGEX, full_text, re.IGNORECASE))
    
    if not matches:
        if full_text:
            events.append({
                "summary": sanitize_summary(full_text),
                "start": base_date,
                "end": base_date + timedelta(days=1),
                "all_day": True
            })
        return events

    for i, match in enumerate(matches):
        time_str = match.group(0)
        start_idx = match.start()
        end_idx = matches[i+1].start() if i + 1 < len(matches) else len(full_text)
        
        # Extract surrounding text as summary
        summary_text = (full_text[:start_idx] if i == 0 else "") + full_text[match.end():end_idx]
        summary = sanitize_summary(summary_text) or "Band Event"
        
        s_dt, e_dt = parse_time_range(time_str, base_date)
        events.append({"summary": summary, "start": s_dt, "end": e_dt, "all_day": False})

    return events

def extract_events(html):
    soup = BeautifulSoup(html, 'html.parser')
    events = []
    
    tables = soup.find_all('table')
    for table in tables:
        # Search backwards up to 5 elements or check full table context for Hawaiian/English month names
        context_nodes = []
        curr = table
        for _ in range(5):
            curr = curr.find_previous()
            if curr:
                context_nodes.append(curr.get_text(separator=" "))
            else:
                break
                
        search_text = (" ".join(context_nodes) + " " + table.get_text(separator=" ")).lower()
        
        table_month = None
        table_year = None
        for m_name, m_num in MONTH_MAP.items():
            if m_name in search_text:
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
                if cell_text:
                    events.extend(process_cell(cell_text, base_date=datetime(table_year, table_month, int(re.match(r'^\d{1,2}', cell_text).group(0))) if re.match(r'^\d{1,2}', cell_text) else None)) if re.match(r'^\d{1,2}', cell_text) else None

    return events
