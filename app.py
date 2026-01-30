# Adapted webhook-enabled app.py (merged from bot.py logic)
# Requirements: flask, python-telegram-bot==20.7, google-generativeai, python-dotenv, gunicorn

import os
import logging
import traceback
import asyncio
import time
import random
from datetime import datetime
from collections import defaultdict, deque
from functools import wraps

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

# 2. Configure logging (ENHANCED)
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
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN or GEMINI_API_KEY(s)")

logger.info(f"✅ Loaded {len(GEMINI_API_KEYS)} Gemini API key(s)")

current_api_key_index = 0
genai.configure(api_key=GEMINI_API_KEYS[current_api_key_index])

# 4. Model & prompts
MODEL_NAME = os.getenv('GEMINI_MODEL', "gemini-2.5-flash")

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
    {"darja": "بصحتك", "french": "À ta santé / Bon appétit", "english": "Cheers / Enjoy your meal", "pronunciation": "bsahtek"},
    {"darja": "نشوفك غدوة", "french": "À demain", "english": "See you tomorrow", "pronunciation": "nshufek ghodwa"},
    {"darja": "وين راك؟", "french": "Où es-tu?", "english": "Where are you?", "pronunciation": "win rak?"},
    {"darja": "ربي يحفظك", "french": "Que Dieu te protège", "english": "May God protect you", "pronunciation": "rabbi yehfadek"},
    {"darja": "ما تقلقش", "french": "Ne t'inquiète pas", "english": "Don't worry", "pronunciation": "ma t'galaksh"},
]

EXAMPLES_LIBRARY = {
    "greetings": [
        {"darja": "السلام عليكم", "french": "Paix sur vous", "english": "Peace be upon you", "pronunciation": "salam aleykum"},
        {"darja": "لاباس عليك", "french": "Pas de mal sur toi", "english": "Are you well?", "pronunciation": "labas alik"},
        {"darja": "مرحبا", "french": "Bienvenue", "english": "Welcome", "pronunciation": "marhaba"},
    ],
    "food": [
        {"darja": "عطيني الخبز", "french": "Donne-moi le pain", "english": "Give me the bread", "pronunciation": "atini el khobz"},
        {"darja": "هذا بنين", "french": "C'est délicieux", "english": "This is delicious", "pronunciation": "hadha bnin"},
        {"darja": "واش عندك لاكل؟", "french": "As-tu de la nourriture?", "english": "Do you have food?", "pronunciation": "wash andek lakl?"},
    ],
    "daily": [
        {"darja": "نروح للخدمة", "french": "Je vais au travail", "english": "I'm going to work", "pronunciation": "nrouh lel khedma"},
        {"darja": "شكون هذا؟", "french": "Qui est-ce?", "english": "Who is this?", "pronunciation": "shkoun hadha?"},
        {"darja": "برك شوية", "french": "Juste un peu", "english": "Just a little", "pronunciation": "berk shwiya"},
    ],
    "slang": [
        {"darja": "والو", "french": "Rien", "english": "Nothing", "pronunciation": "walou"},
        {"darja": "بزاف", "french": "Beaucoup", "english": "A lot", "pronunciation": "bezaf"},
        {"darja": "يا حسرة", "french": "Quel dommage", "english": "What a pity", "pronunciation": "ya hasra"},
    ]
}

def get_system_prompt(dialect='standard'):
    dialect_desc = DIALECT_PROMPTS.get(dialect, DIALECT_PROMPTS['standard'])
    return f"""You are an expert translator specialized in {dialect_desc}. 

CRITICAL TRANSLATION RULES:
1. If input contains ARABIC SCRIPT (Darja) → Translate to: French and English.
2. If input is in FRENCH or ENGLISH → Translate to natural {dialect_desc} with Arabic script.
3. Always include cultural notes for idioms/expressions in ENGLISH.
4. Always include pronunciation guide in Latin characters for any Darja output.

DETECTION RULES:
- If you see Arabic letters (ا ب ت ث...) → Input is Darja
- If you see only Latin letters (a-z, A-Z) → Input is French/English
- Translate accordingly

OUTPUT FORMAT:
For Darja input (Arabic script):
🔤 **Original (Darja):** [text]
🗣️ **Pronunciation:** [latin characters]
🇫🇷 **French:** [translation]
🇬🇧 **English:** [translation]
💡 **Note:** [cultural explanation in ENGLISH]

For French/English input (Latin script):
🔤 **Original:** [text]
🇩🇿 **Darja:** [translation in Arabic script]
🗣️ **Pronunciation:** [latin characters]
💡 **Note:** [cultural explanation in ENGLISH]

IMPORTANT: Always output Darja translations in ARABIC SCRIPT, never in Latin characters only.
"""

# 5. API Key rotation & model initialization
def rotate_api_key():
    global current_api_key_index
    if len(GEMINI_API_KEYS) > 1:
        current_api_key_index = (current_api_key_index + 1) % len(GEMINI_API_KEYS)
        genai.configure(api_key=GEMINI_API_KEYS[current_api_key_index])
        logger.info(f"🔄 Rotated to API key #{current_api_key_index + 1}")
        return True
    return False

def initialize_models():
    models = {}
    for dialect in DIALECT_PROMPTS.keys():
        try:
            models[dialect] = genai.GenerativeModel(
                model_name=MODEL_NAME,
                system_instruction=get_system_prompt(dialect)
            )
            logger.info(f"✅ Initialized model for {dialect} dialect")
        except Exception as e:
            logger.error(f"❌ Failed to initialize {dialect} model: {e}")
    return models

models = initialize_models()

# 6. Retry decorator
def retry_on_failure(max_retries=3, delay=2):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    if 'quota' in error_str or 'rate' in error_str or '429' in error_str or 'resource_exhausted' in error_str:
                        logger.warning(f"⚠️ Quota/Rate limit hit on attempt {attempt + 1}: {e}")
                        if rotate_api_key():
                            global models
                            models = initialize_models()
                            logger.info("🔄 Models reinitialized with new API key")
                            await asyncio.sleep(1)
                            continue
                    if attempt < max_retries - 1:
                        wait_time = delay * (attempt + 1)
                        logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
                        logger.info(f"⏳ Waiting {wait_time}s before retry...")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"❌ All {max_retries} attempts failed")
                        raise last_error
            raise last_error if last_error else Exception("Unknown error")
        return wrapper
    return decorator

@retry_on_failure(max_retries=3, delay=2)
async def translate_text(text: str, user_id: int, include_context=False) -> dict:
    start_time = time.time()
    try:
        user = user_data[user_id]
        dialect = user['dialect']
        model = models.get(dialect)
        if not model:
            logger.error(f"❌ Model not found for dialect: {dialect}")
            raise Exception(f"Model not available for {dialect}")

        if include_context and user['context_mode'] and user['context']:
            context_text = "\n".join([f"Previous: {c}" for c in user['context'][-3:]])
            full_text = f"{context_text}\n\nCurrent: {text}"
        else:
            full_text = text

        logger.info(f"🔄 Calling Gemini API (Key #{current_api_key_index + 1}) for user {user_id}...")
        response = model.generate_content(full_text)

        result_text = response.text if response.text else "⚠️ Empty response from AI."

        # Update context & stats
        if user['context_mode']:
            user['context'].append(text)
            if len(user['context']) > 5:
                user['context'].pop(0)

        user['stats']['total_translations'] += 1
        user['stats']['words_translated'] += len(text.split())
        has_arabic = any('\u0600' <= c <= '\u06FF' for c in text)
        detected_lang = "Darja" if has_arabic else "English/French"
        user['stats']['languages_used'].add(detected_lang)

        processing_time = time.time() - start_time
        logger.info(f"⚡ Processing time: {processing_time:.2f}s")

        return {
            'text': result_text,
            'original': text,
            'detected_lang': detected_lang,
            'dialect': dialect
        }

    except Exception as e:
        logger.error("❌ TRANSLATION FAILED: %s", e)
        logger.error(traceback.format_exc())
        raise

# 7. Handlers (ported from bot.py with same behavior)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🇩🇿 *Marhba! Welcome to Algerian Darja Translator Pro!*", parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """📖 *Complete Feature Guide*

🔹 *Translation:*
• Send Darja (Arabic script) → Get French + English
• Send English/French → Get Darja (Arabic script)

🔹 *Commands:*
/history - View last 10 translations
/save - Bookmark (reply to message)
/saved - View bookmarks
/stats - Your statistics
/dialect [region] - Choose: algiers/oran/constantine/standard
/context on/off - Enable conversation memory
/examples [category] - Browse phrases (greetings/food/daily/slang)
/daily - Get daily Darja phrase
/feedback [text] - Send feedback"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    history = user_data[user_id]['history']
    if not history:
        await update.message.reply_text("📚 No translation history yet. Start translating!")
        return
    history_text = "📚 *Your Recent Translations:*\n\n"
    for i, item in enumerate(reversed(list(history)), 1):
        original = item['original'][:40]
        timestamp = item.get('timestamp', 'N/A')
        history_text += f"{i}. `{original}...`\n   ⏰ {timestamp}\n\n"
    await update.message.reply_text(history_text, parse_mode='Markdown')

async def save_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Please reply to a translation with /save to bookmark it.")
        return
    user_id = update.effective_user.id
    translation_text = update.message.reply_to_message.text
    user_data[user_id]['favorites'].append({
        'text': translation_text,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
    })
    logger.info(f"⭐ Favorite saved by user {user_id}")
    await update.message.reply_text("⭐ Translation saved to favorites!")

async def show_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    favorites = user_data[user_id]['favorites']
    if not favorites:
        await update.message.reply_text("⭐ No favorites yet. Reply to any translation with /save!")
        return
    fav_text = f"⭐ *Your Saved Translations ({len(favorites)}):*\n\n"
    for i, fav in enumerate(favorites[-10:], 1):
        fav_text += f"{i}. {fav['text'][:80]}...\n\n"
    await update.message.reply_text(fav_text, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats = user_data[user_id]['stats']
    stats_text = f"""📊 *Your Translation Statistics:*

📝 Total Translations: {stats['total_translations']}
📖 Words Translated: {stats['words_translated']}
🌍 Languages Used: {len(stats['languages_used'])}
⭐ Saved Favorites: {len(user_data[user_id]['favorites'])}
🗺️ Current Dialect: {user_data[user_id]['dialect'].title()}
🧠 Context Mode: {'✅ ON' if user_data[user_id]['context_mode'] else '❌ OFF'}"""
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def dialect_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        current = user_data[user_id]['dialect']
        await update.message.reply_text(
            f"🗺️ *Current Dialect:* {current.title()}\n\n"
            f"*Available:* standard, algiers, oran, constantine\n\n"
            f"Usage: `/dialect oran`",
            parse_mode='Markdown'
        )
        return
    dialect = context.args[0].lower()
    if dialect in DIALECT_PROMPTS:
        user_data[user_id]['dialect'] = dialect
        logger.info(f"🗺️ User {user_id} changed dialect to {dialect}")
        await update.message.reply_text(f"✅ Dialect changed to: {dialect.title()}")
    else:
        await update.message.reply_text("❌ Invalid dialect. Choose: standard, algiers, oran, or constantine")

async def context_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        status = "ON ✅" if user_data[user_id]['context_mode'] else "OFF ❌"
        await update.message.reply_text(
            f"🧠 *Context Mode:* {status}\n\n"
            f"Usage: `/context on` or `/context off`",
            parse_mode='Markdown'
        )
        return
    mode = context.args[0].lower()
    if mode == 'on':
        user_data[user_id]['context_mode'] = True
        await update.message.reply_text("✅ Context mode enabled!")
    elif mode == 'off':
        user_data[user_id]['context_mode'] = False
        user_data[user_id]['context'] = []
        await update.message.reply_text("❌ Context mode disabled.")
    else:
        await update.message.reply_text("⚠️ Use: /context on or /context off")

async def examples_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "📖 *Phrase Library*\n\n"
            "Categories: greetings, food, daily, slang\n\n"
            "Usage: `/examples greetings`",
            parse_mode='Markdown'
        )
        return
    cat = context.args[0].lower()
    if cat in EXAMPLES_LIBRARY:
        txt = f"📖 *{cat.upper()} Phrases:*\n\n"
        for p in EXAMPLES_LIBRARY[cat]:
            txt += f"🇩🇿 {p['darja']}\n🗣️ {p['pronunciation']}\n🇬🇧 {p['english']}\n\n"
        await update.message.reply_text(txt, parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Category not found. Use /examples to see available categories.")

async def daily_phrase_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phrase = random.choice(DAILY_PHRASES)
    daily_text = f"""🎯 *Daily Darja Phrase:*

🇩🇿 {phrase['darja']}
🗣️ {phrase['pronunciation']}
🇫🇷 {phrase['french']}
🇬🇧 {phrase['english']}"""
    await update.message.reply_text(daily_text, parse_mode='Markdown')

async def notify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.args and len(context.args) > 0:
        mode = context.args[0].lower()
        user_data[user_id]['daily_phrase_enabled'] = (mode == 'on')
        await update.message.reply_text(f"🔔 Daily notifications: {mode.upper()}")
    else:
        status = "ON" if user_data[user_id]['daily_phrase_enabled'] else "OFF"
        await update.message.reply_text(f"🔔 Daily notifications: {status}")

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and len(context.args) > 0:
        feedback = ' '.join(context.args)
        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"
        logger.info(f"💬 FEEDBACK from @{username} (ID: {user_id}): {feedback}")
        await update.message.reply_text("✅ Thank you for your feedback!")
    else:
        await update.message.reply_text("💬 Usage: /feedback Your message here")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    logger.info(f"🎤 Voice message received from @{username} (ID: {user_id})")
    await update.message.reply_text(
        "🎤 Voice message received!\n\n"
        "⚠️ Voice-to-text feature requires additional setup (Whisper).\n"
        "For now, please send text messages.\n\n"
        "Check the VOICE_IMPLEMENTATION_GUIDE.md for setup instructions!"
    )

# Message handler, inline queries and callbacks (same behavior as bot.py)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    user_id = update.effective_user.id
    if not user_text:
        return
    await update.message.chat.send_action(action="typing")
    try:
        result = await translate_text(user_text, user_id, include_context=True)
        user_data[user_id]['history'].append({
            'original': user_text,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
        })
        keyboard = [
            [
                InlineKeyboardButton("⭐ Save", callback_data=f"save_{user_id}"),
                InlineKeyboardButton("💡 Help", callback_data=f"help_{user_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        detection_info = f"\n\n🔍 *Detected:* {result['detected_lang']} | *Dialect:* {result['dialect'].title()}"
        await update.message.reply_text(
            result['text'] + detection_info,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    except Exception as e:
        error_msg = str(e).lower()
        if 'quota' in error_msg or 'rate' in error_msg or 'resource_exhausted' in error_msg:
            await update.message.reply_text(
                "⚠️ *You exceeded your requests limit*\n\n"
                "• Wait a few minutes and try again\n"
                "• Contact the developer for assistance",
                parse_mode='Markdown'
            )
        elif 'invalid' in error_msg or 'format' in error_msg:
            await update.message.reply_text(
                "⚠️ *Invalid Input*\n\n"
                "Please send plain short text.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ *Translation Failed*\n\n"
                f"Error: {str(e)[:100]}\n\n"
                "Please try again or contact support if this persists.",
                parse_mode='Markdown'
            )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("save_"):
        user_id = int(data.split("_")[1])
        user_data[user_id]['favorites'].append({
            'text': query.message.text,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M')
        })
        await query.message.reply_text("⭐ Saved to favorites!")
    elif data.startswith("help_"):
        await query.message.reply_text("📖 Use /help for complete feature guide!")

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.inline_query.query
    if not q:
        return
    try:
        user_id = update.inline_query.from_user.id
        result = await translate_text(q, user_id, include_context=False)
        results = [
            InlineQueryResultArticle(
                id="1",
                title=f"Translate: {q[:30]}...",
                description=f"Detected: {result['detected_lang']}",
                input_message_content=InputTextMessageContent(
                    message_text=result['text'],
                    parse_mode='Markdown'
                )
            )
        ]
        await update.inline_query.answer(results, cache_time=10)
    except Exception as e:
        logger.error(f"Inline query error: {e}")

async def post_init(application: Application):
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("help", "Feature guide"),
        BotCommand("examples", "Phrase library"),
        BotCommand("history", "Recent translations"),
        BotCommand("stats", "Your statistics"),
        BotCommand("dialect", "Change dialect"),
        BotCommand("daily", "Daily phrase")
    ]
    await application.bot.set_my_commands(commands)
    logger.info("✅ Bot commands registered")

# 8. Build PTB application (shared instance)
ptb_app = Application.builder().token(TELEGRAM_TOKEN).connection_pool_size(8).post_init(post_init).build()

# Register handlers
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(CommandHandler("help", help_command))
ptb_app.add_handler(CommandHandler("history", history_command))
ptb_app.add_handler(CommandHandler("save", save_favorite))
ptb_app.add_handler(CommandHandler("saved", show_favorites))
ptb_app.add_handler(CommandHandler("stats", stats_command))
ptb_app.add_handler(CommandHandler("dialect", dialect_command))
ptb_app.add_handler(CommandHandler("context", context_command))
ptb_app.add_handler(CommandHandler("examples", examples_command))
ptb_app.add_handler(CommandHandler("daily", daily_phrase_command))
ptb_app.add_handler(CommandHandler("notify", notify_command))
ptb_app.add_handler(CommandHandler("feedback", feedback_command))
ptb_app.add_handler(MessageHandler(filters.VOICE, handle_voice))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
ptb_app.add_handler(CallbackQueryHandler(button_callback))
ptb_app.add_handler(InlineQueryHandler(inline_query))

# 9. Flask App and webhook route
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "Bot (webhook) is running."

@flask_app.route('/webhook', methods=['POST'])
async def webhook():
    """Handle incoming Telegram updates forwarded by Telegram to our webhook."""
    try:
        payload = request.get_json(force=True)
        update = Update.de_json(payload, ptb_app.bot)
        # Process update with the running Application
        await ptb_app.process_update(update)
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        logger.error(traceback.format_exc())
        return "Error", 500

# 10. Initialization helper (initialize PTB and set Telegram webhook if provided)
async def initialize_bot():
    logger.info("Initializing bot application and models...")
    # (re)initialize models if necessary
    global models
    models = initialize_models()
    await ptb_app.initialize()
    webhook_url = os.getenv('TELEGRAM_WEBHOOK_URL')
    if webhook_url:
        try:
            await ptb_app.bot.set_webhook(webhook_url)
            logger.info(f"✅ Webhook set to: {webhook_url}")
        except Exception as e:
            logger.error(f"❌ Failed to set webhook: {e}")
    else:
        logger.warning("No TELEGRAM_WEBHOOK_URL set. Webhook not configured; bot will not receive updates from Telegram.")

# Run initialization at import / start time so container is ready when requests arrive
try:
    asyncio.get_event_loop().run_until_complete(initialize_bot())
except RuntimeError:
    # In some environments there is no running event loop; create and run one
    asyncio.run(initialize_bot())

# If running locally for debugging, you can use: flask_app.run(host='0.0.0.0', port=8080)
# In production on Koyeb/Gunicorn, run the module with gunicorn:
# gunicorn -w 4 -b 0.0.0.0:8080 "app:flask_app"
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)
