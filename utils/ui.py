from fastapi.templating import Jinja2Templates
from utils.common import from_json, to_json
import os

# Initialize templates
templates = Jinja2Templates(directory="templates")

# Add custom filters
templates.env.filters['from_json'] = from_json
templates.env.filters['to_json'] = to_json
