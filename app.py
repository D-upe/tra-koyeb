import os
import logging
import json
import traceback
import asyncio
import time
from datetime import datetime, timedelta
from collections import defaultdict, deque
from functools import wraps

# Webhook specific imports
from flask import Flask, request
from dotenv import load_dotenv

# Telegram imports
from telegram import (
    Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, 
    InlineQueryResultArticle, InputTextMessageContent
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, 
    InlineQueryHandler, filters, ContextTypes
)
import google.generativeai as genai

# 1. Load environment variables
load_dotenv()

# 2. Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot_activity.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 3. API Key Check
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEYS = [
    os.getenv('GEMINI_API_KEY'),
    os.getenv('GEMINI_API_KEY_2'),
    os.getenv('GEMINI_API_KEY_3')
]
GEMINI_API_KEYS = [k for k in GEMINI_API_KEYS if k]

if not TELEGRAM_TOKEN or not GEMINI_API_KEYS:
    logger.error("❌ MISSING KEYS: Check your environment variables")
    exit(1)

current_api_key_index = 0
genai.configure(api_key=GEMINI_API_KEYS[current_api_key_index])
MODEL_NAME = "gemini-2.0-flash" # Note: Adjusted to a currently available stable model

# 4. User data storage
user_data = defaultdict(lambda: {
    'history': deque(maxlen=10),
    'favorites': [],
    'context_mode': False,
    'context': [],
    'stats': {'total_translations': 0, 'words_translated': 0, 'languages_used': set()},
    'dialect': 'standard',
    'daily_phrase_enabled': False,
    'last_daily_phrase': None
})

DIALECT_PROMPTS = {
    'standard': 'Algerian Arabic (Darja)',
    'algiers': 'Algerian Arabic (Darja) from Algiers region',
    'oran': 'Algerian Arabic (Darja) from Oran region (Western Algeria)',
    'constantine': 'Algerian Arabic (Darja) from Constantine region (Eastern Algeria)'
}

DAILY_PHRASES = [
    {"darja": "صباح الخير", "french": "Bonjour", "english": "Good morning", "pronunciation": "sbah el khir"},
    {"darja": "كيفاش راك؟", "french": "Comment vas-tu?", "english": "How are you?", "pronunciation": "kifash rak?"},
    {"darja": "بصحتك", "french": "À ta santé / Bon appétit", "english": "Cheers / Enjoy your meal", "pronunciation": "bsahtek"}
]

EXAMPLES_LIBRARY = {
    "greetings": [{"darja": "السلام عليكم", "french": "Paix sur vous", "english": "Peace be upon you", "pronunciation": "salam aleykum"}],
    "food": [{"darja": "عطيني الخبز", "french": "Donne-moi le pain", "english": "Give me the bread", "pronunciation": "atini el khobz"}]
}

# 5. Helper Functions
def get_system_prompt(dialect='standard'):
    dialect_desc = DIALECT_PROMPTS.get(dialect, DIALECT_PROMPTS['standard'])
    return f"""You are an expert translator specialized in {dialect_desc}. 
    Rules: Arabic script Darja <-> French/English. Always include pronunciation and cultural notes."""

def rotate_api_key():
    global current_api_key_index
    if len(GEMINI_API_KEYS) > 1:
        current_api_key_index = (current_api_key_index + 1) % len(GEMINI_API_KEYS)
        genai.configure(api_key=GEMINI_API_KEYS[current_api_key_index])
        return True
    return False

def initialize_models():
    models = {}
    for dialect in DIALECT_PROMPTS.keys():
        models[dialect] = genai.GenerativeModel(model_name=MODEL_NAME, system_instruction=get_system_prompt(dialect))
    return models

models = initialize_models()

def retry_on_failure(max_retries=3, delay=2):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try: return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if 'quota' in str(e).lower() and rotate_api_key():
                        global models
                        models = initialize_models()
                        continue
                    await asyncio.sleep(delay)
            raise last_error
        return wrapper
    return decorator

@retry_on_failure()
async def translate_text(text: str, user_id: int, include_context=False) -> dict:
    user = user_data[user_id]
    dialect = user['dialect']
    model = models.get(dialect)
    full_text = f"Context: {user['context'][-3:]}\nText: {text}" if include_context and user['context_mode'] else text
    response = model.generate_content(full_text)
    
    # Simple lang detection logic
    has_arabic = any('\u0600' <= c <= '\u06FF' for c in text)
    return {'text': response.text, 'detected_lang': "Darja" if has_arabic else "French/English", 'dialect': dialect}

# 6. Telegram Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🇩🇿 *Marhba!* Algerian Darja Translator is live on Koyeb!", parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.chat.send_action(action="typing")
    try:
        result = await translate_text(update.message.text, user_id, True)
        keyboard = [[InlineKeyboardButton("⭐ Save", callback_data=f"save_{user_id}")]]
        await update.message.reply_text(f"{result['text']}\n\n🔍 *Detected:* {result['detected_lang']}", 
                                       parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await update.message.reply_text("❌ Translation failed. Try again later.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("save_"):
        await query.message.reply_text("⭐ Saved to favorites!")

async def post_init(application: Application):
    await application.bot.set_my_commands([BotCommand("start", "Start the bot")])

# 7. Flask & Webhook Setup
flask_app = Flask(__name__)

# Build the PTB Application
ptb_app = (
    Application.builder()
    .token(TELEGRAM_TOKEN)
    .post_init(post_init)
    .build()
)

# Register Handlers to PTB
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(CallbackQueryHandler(button_callback))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

@flask_app.route('/')
def index():
    return "Bot is running."

@flask_app.route('/webhook', methods=['POST'])
async def webhook():
    """Handle incoming Telegram updates"""
    update = Update.de_json(request.get_json(force=True), ptb_app.bot)
    async with ptb_app:
        await ptb_app.process_update(update)
    return "OK", 200

if __name__ == '__main__':
    # Initialize PTB before starting Flask
    loop = asyncio.get_event_loop()
    loop.run_until_complete(ptb_app.initialize())
    
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)
