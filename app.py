# app.py
import os
import logging
import traceback
import asyncio
import time
import random
from datetime import datetime
from collections import defaultdict, deque
from functools import wraps

from flask import Flask, request, jsonify
from dotenv import load_dotenv

from telegram import (
    Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    InlineQueryHandler, filters, ContextTypes
)

import google.generativeai as genai

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ===== Environment & API keys =====
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEYS = [os.getenv(f'GEMINI_API_KEY{suffix}') for suffix in ['', '_2', '_3']]
GEMINI_API_KEYS = [k for k in GEMINI_API_KEYS if k]

current_api_key_index = 0
genai.configure(api_key=GEMINI_API_KEYS[current_api_key_index])
MODEL_NAME = os.getenv('GEMINI_MODEL', "gemini-1.5-flash") # Use 1.5 flash for stability

# ===== Data Structures =====
user_data = defaultdict(lambda: {
    'history': deque(maxlen=10),
    'favorites': [],
    'context_mode': False,
    'context': [],
    'stats': {'total_translations': 0, 'words_translated': 0, 'languages_used': set()},
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
1. INPUT = ARABIC SCRIPT -> OUTPUT = French AND English.
2. INPUT = LATIN SCRIPT -> OUTPUT = Darja (Arabic script) AND French AND English.
3. YOU MUST ALWAYS PROVIDE A FRENCH TRANSLATION.

REQUIRED OUTPUT FORMAT:
🔤 **Original:** [text]
🇩🇿 **Darja:** [Arabic script]
🗣️ **Pronunciation:** [latin characters]
🇫🇷 **French:** [translation]
🇬🇧 **English:** [translation]
💡 **Note:** [cultural explanation in English]
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

# GLOBAL OBJECTS
models = initialize_models()
ptb_app = None

async def translate_text(text: str, user_id: int):
    user = user_data[user_id]
    model = models.get(user['dialect'])
    response = model.generate_content(text)
    return response.text if response.text else "⚠️ Error generating translation."

# ===== Handlers =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.effective_user.id
    await update.message.chat.send_action(action="typing")
    
    try:
        result_text = await translate_text(update.message.text, user_id)
        await update.message.reply_text(result_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Translation error: {e}")
        await update.message.reply_text("❌ Connection error. Please try again.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🇩🇿 *Marhba!* I am ready. Send me anything to translate!")

# ===== App Setup =====
async def build_ptb_app():
    global ptb_app
    if ptb_app: return
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    await app.initialize()
    ptb_app = app
    logger.info("✅ PTB Application Initialized")

flask_app = Flask(__name__)

# Replace your current /webhook and bottom of file with this:

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    try:
        global ptb_app, models
        # Initialize only if not already done
        if ptb_app is None:
            models = initialize_models()
            # Use a simpler way to run the async initialization
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(build_ptb_app())
            loop.close()

        payload = request.get_json(force=True)
        update = Update.de_json(payload, ptb_app.bot)
        
        # Process the update
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(ptb_app.process_update(update))
        loop.close()
        
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook Error: {e}")
        return "Error", 500

if __name__ == '__main__':
    # For local testing only
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)
