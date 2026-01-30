# app.py
import os
import logging
import asyncio
from collections import defaultdict, deque
from flask import Flask, request
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai

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
raw_keys = [os.getenv(f'GEMINI_API_KEY{suffix}') for suffix in ['', '_2', '_3']]
GEMINI_API_KEYS = [k for k in raw_keys if k]

if not TELEGRAM_TOKEN or not GEMINI_API_KEYS:
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN or GEMINI_API_KEY(s)")

# UPDATED: Set default model to Gemini 2.5 Flash
DEFAULT_MODEL = "gemini-2.5-flash"
BASE_URL = os.getenv('KOYEB_PUBLIC_URL', '').rstrip('/')

# ===== Data Structures =====
user_data = defaultdict(lambda: {'history': deque(maxlen=10), 'dialect': 'standard'})

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
2. IF INPUT IS LATIN SCRIPT -> YOU MUST PROVIDE THE DARJA TRANSLATION IN ARABIC SCRIPT.
3. YOU MUST ALWAYS PROVIDE A FRENCH TRANSLATION.
REQUIRED OUTPUT FORMAT:
🔤 **Original:** [text]
🇩🇿 **Darja:** [Arabic script translation]
🗣️ **Pronunciation:** [latin character pronunciation]
🇫🇷 **French:** [French translation]
🇬🇧 **English:** [English translation]
💡 **Note:** [Short cultural explanation in English]
"""

# ===== Core Functions =====
def get_model(dialect='standard', key_index=0, model_name=DEFAULT_MODEL):
    """Configures and returns a model with a specific API key and version."""
    genai.configure(api_key=GEMINI_API_KEYS[key_index])
    return genai.GenerativeModel(
        model_name=model_name,
        system_instruction=get_system_prompt(dialect)
    )

async def translate_text(text: str, user_id: int):
    user = user_data[user_id]
    
    # Try different versions in order of preference if the first fails
    version_fallback = [DEFAULT_MODEL, "gemini-1.5-flash", "gemini-3-flash"]
    
    for model_ver in version_fallback:
        # Try each API key for this specific model version
        for i, key in enumerate(GEMINI_API_KEYS):
            try:
                model = get_model(user['dialect'], key_index=i, model_name=model_ver)
                response = model.generate_content(text)
                
                if response.candidates:
                    return response.text
                else:
                    return "⚠️ Response blocked by AI safety filters. Please try different wording."
                    
            except Exception as e:
                logger.warning(f"Version {model_ver} with Key {i} failed: {e}")
                continue # Try next key or next version
    
    return "❌ All AI connection attempts failed. Please check API keys or model names."

# ===== Handlers =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    await update.message.chat.send_action(action="typing")
    try:
        result_text = await translate_text(update.message.text, update.effective_user.id)
        await update.message.reply_text(result_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Final Translation Error: {e}")
        await update.message.reply_text("❌ Connection error with AI. Please check logs.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🇩🇿 *Marhba!* Bot is ready with Gemini 2.5. Send text to translate!")

# ===== PTB Application =====
ptb_app = Application.builder().token(TELEGRAM_TOKEN).connection_pool_size(20).build()
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

flask_app = Flask(__name__)

@flask_app.route('/webhook', methods=['POST'])
async def webhook():
    try:
        payload = request.get_json(force=True)
        update = Update.de_json(payload, ptb_app.bot)
        await ptb_app.update_queue.put(update)
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook Error: {e}")
        return "OK", 200

def main():
    import uvicorn
    from asgiref.wsgi import WsgiToAsgi
    port = int(os.environ.get("PORT", 8080))
    asgi_app = WsgiToAsgi(flask_app)

    async def run():
        async with ptb_app:
            await ptb_app.start()
            if BASE_URL:
                await ptb_app.bot.set_webhook(url=f"{BASE_URL}/webhook")
                logger.info(f"🚀 Webhook: {BASE_URL}/webhook")
            
            config = uvicorn.Config(app=asgi_app, host="0.0.0.0", port=port, log_level="info")
            server = uvicorn.Server(config)
            await server.serve()
            await ptb_app.stop()

    asyncio.run(run())

if __name__ == '__main__':
    main()
