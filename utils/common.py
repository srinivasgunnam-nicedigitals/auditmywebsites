import json
import urllib.parse
import re

def from_json(value):
    """Custom Jinja2 filter to parse JSON strings"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except:
            return []
    return value

def to_json(value):
    """Custom Jinja2 filter to convert to JSON string"""
    return json.dumps(value)

def get_unique_filename(url: str) -> str:
    """Generate unique filename using last path segment + domain"""
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    domain = re.sub(r'[^\w\.-]', '-', domain)
    
    path = parsed.path.strip("/")
    if not path or path in ("", "/"):
        page_name = "home"
    else:
        segments = [s for s in path.split("/") if s]
        if segments:
            page_name = segments[-1].split('.')[0]
            page_name = re.sub(r'[^\w\-]', '-', page_name).strip("-").lower()
            if not page_name or page_name in ("index", "home"):
                page_name = "home"
            if len(page_name) > 50:
                page_name = page_name[:47] + "..."
        else:
            page_name = "home"
    
    return f"{page_name}__{domain}"
