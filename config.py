import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WHITELIST = set(map(int, os.getenv("WHITELIST", "").split(",")))
DB_PATH = "history.db"
TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)
PROXY = os.getenv("PROXY")  # http://user:pass@host:port
WB_API_TOKEN = os.getenv("WB_API_TOKEN")  # не используется, но оставлено для будущих нужд