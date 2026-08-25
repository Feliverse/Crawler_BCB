from datetime import date

# URL observed for the BCB metals page
BASE_URL = "https://www.bcb.gob.bo/librerias/indicadores/metales/anteriores.php"

# Default headers to mimic a real browser
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Default date format used by the site (day/month/year)
DATE_FORMAT = "%d/%m/%Y"

# Storage defaults
DB_PATH = "crawler_data.sqlite"

# Rate limit (seconds) between requests when iterating dates
RATE_LIMIT_SECONDS = 1.0
