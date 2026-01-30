# app.py
import os
import logging
import asyncio
from collections import defaultdict, deque

from flask import Flask, request
from dotenv import load_dotenv

# Telegram imports
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes
)

# Gemini client
import google.generativeai as genai

# ===== Load env & logging =====
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ===== Environment & API keys =====
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
# Support for multiple keys to prevent quota errors
GEMINI_API_KEYS = [os.getenv(f'GEMINI_API_KEY{suffix}') for suffix in ['', '_2', '_3']]
GEMINI_API_KEYS = [k for k in GEMINI_API_KEYS if k]

if not TELEGRAM_TOKEN or not GEMINI_API_KEYS:
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN or GEMINI_API_KEY(s)")

genai.configure(api_key=GEMINI_API_KEYS[0])
MODEL_NAME = os.getenv('GEMINI_MODEL', "gemini-1.5-flash")

# ===== Data Structures =====
user_data = defaultdict(lambda: {
    'history': deque(maxlen=10),
    'dialect': 'standard'
})

DIALECT_PROMPTS = {
    'standard': 'Algerian Arabic (Darja)',
    'algiers': 'Algerian Arabic (Darja) from Algiers region',
    'oran': 'Algerian Arabic (Darja) from Oran region',
    'constantine': 'Algerian Arabic (Darja) from Constantine region'
}

def get_system_prompt(dialect='standard'):
    dialect_desc = DIALECT_PROMPTS.get(dialect, DIALECT_PROMPTS['standard'])
    return f"""You are an expert translator for {dialect_desc}.

STRICT RULES:
1. IF INPUT IS ARABIC SCRIPT -> YOU MUST PROVIDE FRENCH AND ENGLISH TRANSLATIONS.
2. IF INPUT IS LATIN SCRIPT (FRENCH/ENGLISH) -> YOU MUST PROVIDE THE DARJA TRANSLATION IN ARABIC SCRIPT.
3. YOU MUST ALWAYS PROVIDE A FRENCH TRANSLATION REGARDLESS OF THE INPUT LANGUAGE.

REQUIRED OUTPUT FORMAT:
🔤 **Original:** [text]
🇩🇿 **Darja:** [Arabic script translation]
🗣️ **Pronunciation:** [latin character pronunciation]
🇫🇷 **French:** [French translation]
🇬🇧 **English:** [English translation]
💡 **Note:** [Short cultural explanation in English]
"""

# ===== Core Functions =====
def initialize_models():
    new_models = {}
    for dialect in DIALECT_PROMPTS.keys():
        new_models[dialect] = genai.GenerativeModel(
            model_name=MODEL_NAME,
            system_instruction=get_system_prompt(dialect)
        )
    return new_models

models = initialize_models()

async def translate_text(text: str, user_id: int):
    user = user_data[user_id]
    model = models.get(user['dialect'])
    response = model.generate_content(text)
    if response and response.text:
        return response.text
    return "⚠️ The AI could not generate a translation. Try a different phrase."

# ===== Handlers =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    await update.message.chat.send_action(action="typing")

    try:
        result_text = await translate_text(update.message.text, user_id)
        await update.message.reply_text(result_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Translation error: {e}")
        await update.message.reply_text("❌ Connection error with AI. Please try again in a moment.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🇩🇿 *Marhba!* I am ready. Send me Darja, French, or English to translate!")

# ===== PTB Application (built at import, no async init) =====
ptb_app = (
    Application.builder()
    .token(TELEGRAM_TOKEN)
    .connection_pool_size(20)
    .build()
)
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# ===== Flask app =====
flask_app = Flask(__name__)

@flask_app.route('/health')
def health():
    return "OK", 200

@flask_app.route('/webhook', methods=['POST'])
async def webhook():
    """Put incoming Telegram updates into PTB's queue (same event loop = no threading errors)."""
    try:
        payload = request.get_json(force=True)
        update = Update.de_json(payload, ptb_app.bot)
        await ptb_app.update_queue.put(update)
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook Error: {e}")
        return "OK", 200

# ===== Run PTB + web server in one event loop (fixes "event loop" / "different thread" errors) =====
def main():
    import uvicorn
    from asgiref.wsgi import WsgiToAsgi

    port = int(os.environ.get("PORT", 8080))
    asgi_app = WsgiToAsgi(flask_app)

    async def run():
        async with ptb_app:  # handles initialize() / shutdown()
            await ptb_app.start()
            logger.info("✅ PTB + Flask webhook running on same event loop")
            config = uvicorn.Config(
                app=asgi_app,
                host="0.0.0.0",
                port=port,
                log_level="info",
            )
            server = uvicorn.Server(config)
            await server.serve()
            await ptb_app.stop()

    asyncio.run(run())

if __name__ == '__main__':
    main()
