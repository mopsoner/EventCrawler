from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
EXPORT_DIR = BASE_DIR / "exports"
DB_PATH = DATA_DIR / "eventcrawler.sqlite"

REGIONS = {
    "london": "https://www.bizouk.com/?region=london",
    "guadeloupe": "https://www.bizouk.com/?region=guadeloupe",
    "paris": "https://www.bizouk.com/?region=paris",
    "rotterdam": "https://www.bizouk.com/?region=rotterdam",
}

BASE_URL = "https://www.bizouk.com"
HEADLESS = os.getenv("EVENTCRAWLER_HEADLESS", "true").lower() == "true"
APP_HOST = os.getenv("EVENTCRAWLER_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("EVENTCRAWLER_PORT", "8000"))

EXTRACTION_MODE = os.getenv("EVENTCRAWLER_EXTRACTION_MODE", "HYBRID").upper()
AI_ENABLED = os.getenv("EVENTCRAWLER_AI_ENABLED", "false").lower() == "true"
MAX_BODY_TEXT = int(os.getenv("EVENTCRAWLER_MAX_BODY_TEXT", "16000"))
