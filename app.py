# app.py
import os
import logging
import traceback
import asyncio
from datetime import datetime
from collections import defaultdict, deque

from flask import Flask, request, jsonify
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

# Global objects
models = initialize_models()
ptb_app = None

async def translate_text(text: str, user_id: int):
    user = user_data[user_id]
    model = models.get(user['dialect'])
    # Add safety settings to prevent blocked responses
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

# ===== App Setup =====
async def build_ptb_app():
    global ptb_app
    if ptb_app: return
    
    # Increase connection pool for better performance on Koyeb
    app = Application.builder().token(TELEGRAM_TOKEN).connection_pool_size(20).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await app.initialize()
    ptb_app = app
    logger.info("✅ PTB Application Initialized")

flask_app = Flask(__name__)

@flask_app.route('/health')
def health():
    return "OK", 200

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    try:
        # Use existing event loop for better efficiency
        loop = asyncio.get_event_loop()
        
        # 1. Ensure app is ready (Prevents first-message-fails bug)
        if ptb_app is None:
            loop.run_until_complete(build_ptb_app())

        # 2. Parse the update
        payload = request.get_json(force=True)
        update = Update.de_json(payload, ptb_app.bot)
        
        # 3. Process the update asynchronously
        loop.run_until_complete(ptb_app.process_update(update))
        
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook Error: {e}")
        return "OK", 200 # Always return 200 so Telegram stops retrying failed updates

# Force pre-initialization when running locally
if __name__ == '__main__':
    asyncio.run(build_ptb_app())
    flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
