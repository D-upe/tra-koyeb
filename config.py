import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ===== General Config =====
PORT = int(os.environ.get("PORT", 8080))
BASE_URL = os.environ.get("KOYEB_PUBLIC_URL", "").rstrip("/")
ADMIN_CONTACT = "@Erivative"

# ===== Database Config =====
DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_PATH = os.environ.get("DATABASE_PATH", "translations.db")

# ===== API Keys =====
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Gemini Keys Rotation
raw_keys = [os.environ.get(f"GEMINI_API_KEY{suffix}") for suffix in ["", "_1", "_2", "_3"]]
GEMINI_API_KEYS = [k for k in raw_keys if k]

# Validate critical keys
if not TELEGRAM_TOKEN:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN")
if not GEMINI_API_KEYS and not GROQ_API_KEY:
    raise ValueError("Missing both GEMINI_API_KEY(s) and GROQ_API_KEY")

# ===== Model Config =====
DEFAULT_MODEL = "gemini-2.0-flash"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

# ===== Payment Config =====
STRIPE_BASIC_LINK = os.environ.get("STRIPE_BASIC_LINK")
STRIPE_PRO_LINK = os.environ.get("STRIPE_PRO_LINK")
STRIPE_UNLIMITED_LINK = os.environ.get("STRIPE_UNLIMITED_LINK")

# ===== TTS Configuration =====
TTS_VOICES = {
    'standard': 'ar-DZ-IsmaelNeural', # Algerian Arabic (Male)
    'algiers': 'ar-DZ-IsmaelNeural',
    'oran': 'ar-DZ-IsmaelNeural',
    'tunis': 'ar-TN-HediNeural',      # Tunisian (Male)
    'morocco': 'ar-MA-JamalNeural',   # Moroccan (Male)
    'egypt': 'ar-EG-SalmaNeural',     # Egyptian (Female)
    'saudi': 'ar-SA-HamedNeural',     # Saudi (Male)
    'fallback': 'ar-SA-ZariyahNeural' # Standard Arabic (Female)
}
