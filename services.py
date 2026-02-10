import os
import logging
import asyncio
import tempfile
import edge_tts
from datetime import datetime
from google import genai
from groq import AsyncGroq
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application

from config import GEMINI_API_KEYS, GROQ_API_KEY, DEFAULT_MODEL, GROQ_MODEL, TTS_VOICES
from database import db
from utils import split_message

logger = logging.getLogger(__name__)

# ===== Dialect Configuration =====
DIALECT_PROMPTS = {
    'standard': 'Algerian Arabic (Darja)',
    'algiers': 'Algerian Arabic (Darja) from Algiers region',
    'oran': 'Algerian Arabic (Darja) from Oran region',
    'constantine': 'Algerian Arabic (Darja) from Constantine region'
}

# ===== Local Dictionary =====
LOCAL_DICTIONARY = {
    'hello': {
        'darja': 'واش راك / سلام',
        'pronunciation': 'Wash rak / Salam',
        'french': 'Bonjour / Salut',
        'english': 'Hello',
        'note': 'Wash rak is typically Algerian'
    },
    'good morning': {
        'darja': 'صباح الخير',
        'pronunciation': 'Sbah el khir',
        'french': 'Bonjour',
        'english': 'Good morning',
        'note': 'Standard greeting'
    },
    'good night': {
        'darja': 'تصبح على خير',
        'pronunciation': 'Tesbah ala khair',
        'french': 'Bonne nuit',
        'english': 'Good night',
        'note': 'Said when parting at night'
    },
    'goodbye': {
        'darja': 'مع السلامة / بسلامة',
        'pronunciation': 'Ma\'a salama / B\'salama',
        'french': 'Au revoir',
        'english': 'Goodbye',
        'note': 'B\'salama is the Algerian short form'
    },
    'how are you': {
        'darja': 'واش راك / كيفاه راك',
        'pronunciation': 'Wash rak / Kifah rak',
        'french': 'Comment ça va',
        'english': 'How are you',
        'note': 'Wash rak is most common in Algeria'
    },
    'thank you': {
        'darja': 'شكرا / بارك الله فيك',
        'pronunciation': 'Choukran / Barak Allah fik',
        'french': 'Merci',
        'english': 'Thank you',
        'note': 'Barak Allah fik is more heartfelt/grateful'
    },
    'please': {
        'darja': 'عفوا / برك الله فيك',
        'pronunciation': '\'Afak / Baraka Allah fik',
        'french': 'S\'il te plaît',
        'english': 'Please',
        'note': 'Literally means "for your sake"'
    },
    'sorry': {
        'darja': 'سمحني / معذرة',
        'pronunciation': 'Smehli / Ma\'zerta',
        'french': 'Pardon / Désolé',
        'english': 'Sorry / Excuse me',
        'note': 'Smehli literally means "forgive me"'
    },
    'yes': {
        'darja': 'نعم / واه / إييه',
        'pronunciation': 'Na\'am / Wah / Eyeh',
        'french': 'Oui',
        'english': 'Yes',
        'note': 'Wah and Eyeh are casual affirmations'
    },
    'no': {
        'darja': 'لا / أواه',
        'pronunciation': 'La / Owah',
        'french': 'Non',
        'english': 'No',
        'note': 'Owah is Algerian pronunciation'
    },
    'food': {
        'darja': 'الماكل / الطعام',
        'pronunciation': 'El-makul / At-ta\'am',
        'french': 'Nourriture',
        'english': 'Food',
        'note': 'El-makul is specifically Algerian dialect'
    },
    'water': {
        'darja': 'الماء / الما',
        'pronunciation': 'El-ma\' / El-ma',
        'french': 'Eau',
        'english': 'Water',
        'note': 'El-ma is the Algerian pronunciation'
    },
    'bread': {
        'darja': 'الخبز / الرغيف',
        'pronunciation': 'El-khobz / Er-raghif',
        'french': 'Pain',
        'english': 'Bread',
        'note': 'Essential part of every Algerian meal'
    },
    'coffee': {
        'darja': 'القهوة',
        'pronunciation': 'El-qahwa',
        'french': 'Café',
        'english': 'Coffee',
        'note': 'Algerian coffee culture is strong'
    },
    'tea': {
        'darja': 'الأتاي / الشاي',
        'pronunciation': 'El-atay / Esh-shay',
        'french': 'Thé',
        'english': 'Tea',
        'note': 'Mint tea is traditional'
    },
    'mother': {
        'darja': 'مّي / الوالدة',
        'pronunciation': 'Mmi / El-walida',
        'french': 'Mère',
        'english': 'Mother',
        'note': 'Mmi is the most intimate term'
    },
    'father': {
        'darja': 'بابا / الوالد',
        'pronunciation': 'Baba / El-walid',
        'french': 'Père',
        'english': 'Father',
        'note': 'Baba is affectionate Algerian term'
    },
    'brother': {
        'darja': 'خوي',
        'pronunciation': 'Khouya',
        'french': 'Frère',
        'english': 'Brother',
        'note': 'Also used to address close male friends'
    },
    'sister': {
        'darja': 'ختي',
        'pronunciation': 'Khti',
        'french': 'Sœur',
        'english': 'Sister',
        'note': 'Also used to address close female friends'
    },
    'friend': {
        'darja': 'الصاحب / الصاحبي',
        'pronunciation': 'Es-sahib / Es-sahbi',
        'french': 'Ami',
        'english': 'Friend',
        'note': 'Es-sahbi literally means "my companion"'
    },
    'i love you': {
        'darja': 'نحبك',
        'pronunciation': 'Nhebbek',
        'french': 'Je t\'aime',
        'english': 'I love you',
        'note': 'Can be used for romantic or familial love'
    },
    'very good': {
        'darja': 'مليح / بزاف مليح',
        'pronunciation': 'Mlih / Bzzaf mlih',
        'french': 'Très bien',
        'english': 'Very good',
        'note': 'Mlih is the most common Algerian term'
    },
    'i don\'t understand': {
        'darja': 'ما فهمتش',
        'pronunciation': 'Ma fhemtsh',
        'french': 'Je ne comprends pas',
        'english': 'I don\'t understand',
        'note': 'The "sh" ending is the Algerian negation'
    },
    'where is': {
        'darja': 'وين رايح / وين هو',
        'pronunciation': 'Win rayeh / Win huwa',
        'french': 'Où est',
        'english': 'Where is',
        'note': 'Win is Algerian for "where"'
    },
    'how much': {
        'darja': 'شحال / بشحال',
        'pronunciation': 'Shhal / Beshhal',
        'french': 'Combien',
        'english': 'How much',
        'note': 'Essential for shopping in markets'
    },
    'where are you going': {
        'darja': 'وين راك رايح',
        'pronunciation': 'Win rak rayeh',
        'french': 'Où vas-tu',
        'english': 'Where are you going',
        'note': 'Win means where'
    },
    'i am hungry': {
        'darja': 'راني جيعان',
        'pronunciation': 'Rani ji\'an',
        'french': 'J\'ai faim',
        'english': 'I am hungry',
        'note': 'Rani means "I am" in this context'
    },
    'i am thirsty': {
        'darja': 'راني عطشان',
        'pronunciation': 'Rani \'atshan',
        'french': 'J\'ai soif',
        'english': 'I am thirsty',
        'note': 'Used for needing water'
    },
    'beautiful': {
        'darja': 'شباب / شابة',
        'pronunciation': 'Shbab (m) / Shaba (f)',
        'french': 'Beau / Belle',
        'english': 'Beautiful / Handsome',
        'note': 'Very common Algerian word'
    },
    'nothing': {
        'darja': 'والو',
        'pronunciation': 'Wallou',
        'french': 'Rien',
        'english': 'Nothing',
        'note': 'Derived from Arabic "wa-la-shay"'
    }
}

class DictionaryFallback:
    """Local dictionary fallback when APIs fail."""
    
    @staticmethod
    def normalize(text: str) -> str:
        """Normalize text for lookup."""
        return text.lower().strip().rstrip('?').rstrip('!').rstrip('.')
    
    @staticmethod
    def find_match(text: str) -> dict:
        """Find best match in local dictionary."""
        normalized = DictionaryFallback.normalize(text)
        
        # Direct match
        if normalized in LOCAL_DICTIONARY:
            return LOCAL_DICTIONARY[normalized]
        
        # Partial match - check if any key is contained in text
        for key, value in LOCAL_DICTIONARY.items():
            if key in normalized or normalized in key:
                return value
        
        return None
    
    @staticmethod
    def format_translation(text: str, match: dict) -> str:
        """Format dictionary result like API response."""
        return (
            f"🔤 **Original:** {text}\n"
            f"🇩🇿 **Darja:** {match['darja']}\n"
            f"🗣️ **Pronunciation:** {match['pronunciation']}\n"
            f"🇫🇷 **French:** {match['french']}\n"
            f"🇬🇧 **English:** {match['english']}\n"
            f"💡 **Note:** {match['note']}\n\n"
            f"⚠️ *Using offline dictionary (API unavailable)*"
        )
    
    @staticmethod
    def get_all_words() -> str:
        """Get list of all available dictionary words."""
        words = sorted(LOCAL_DICTIONARY.keys())
        return "📚 *Available in offline dictionary:*\n\n" + "\n".join([f"• {w}" for w in words])

dictionary_fallback = DictionaryFallback()

def get_system_prompt(dialect='standard', context_history=None):
    dialect_desc = DIALECT_PROMPTS.get(dialect, DIALECT_PROMPTS['standard'])
    prompt = f"You are an expert translator for {dialect_desc}.\n"
    
    if context_history:
        history_list = [h['text'] for h in list(context_history)]
        prompt += f"Recent context for reference: {history_list}\n"

    prompt += """
STRICT RULES:
1. IF INPUT IS ARABIC SCRIPT -> PROVIDE FRENCH AND ENGLISH.
2. IF INPUT IS LATIN SCRIPT -> PROVIDE DARJA (ARABIC SCRIPT) AND FRENCH AND ENGLISH.
REQUIRED OUTPUT FORMAT:
🔤 **Original:** [text]
🇩🇿 **Darja:** [Arabic script]
🗣️ **Pronunciation:** [latin]
🇫🇷 **French:** [translation]
🇬🇧 **English:** [translation]
💡 **Note:** [Short cultural note]
"""
    return prompt

# ===== Core Logic =====
async def translate_text(text: str, user_id: int):
    user = await db.get_user(user_id)
    history = await db.get_history(user_id) if user['context_mode'] else None
    dialect = user['dialect']
    
    # 0. Check Verified Translations first (Highest Priority)
    try:
        verified = await db.get_verified_translation(text, dialect)
        if verified:
            logger.info(f"Verified translation hit for: {text[:50]}...")
            await db.add_history(user_id, text)
            return f"✅ *Verified Translation*\n\n{verified}"
    except Exception as e:
        logger.error(f"Error checking verified translations: {e}")
        # Continue to API fallback
    
    # Check cache first (only for dialect-specific translations without context)
    if not user['context_mode'] or not history:
        cached = await db.get_cached_translation(text, dialect)
        if cached:
            logger.info(f"Cache hit for: {text[:50]}...")
            await db.add_history(user_id, text)
            return f"⚡ *Cached*\n\n{cached}"
    
    version_fallback = [DEFAULT_MODEL, "gemini-2.0-flash-exp", "gemini-2.5-flash", "gemini-1.5-flash"]
    
    api_error = None
    
    # 1. Try Gemini first
    for model_ver in version_fallback:
        for i, key in enumerate(GEMINI_API_KEYS):
            try:
                client = genai.Client(api_key=key)
                response = client.models.generate_content(
                    model=model_ver,
                    contents=text,
                    config={
                        'system_instruction': get_system_prompt(dialect, history)
                    }
                )
                
                if response.text:
                    translation = response.text
                    await db.add_history(user_id, text)
                    
                    # Cache the translation (only if no context was used)
                    if not user['context_mode'] or not history:
                        await db.cache_translation(text, dialect, translation)
                        logger.info(f"Cached translation for: {text[:50]}...")
                    
                    return translation
                api_error = "Safety filter blocked response"
            except Exception as e:
                api_error = str(e)
                logger.warning(f"Gemini error with {model_ver}, key {i}: {e}")
                continue
    
    # 2. Try Groq as fallback if Gemini fails
    if GROQ_API_KEY:
        try:
            logger.info("Attempting Groq fallback...")
            client = AsyncGroq(api_key=GROQ_API_KEY)
            
            response = await client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": get_system_prompt(dialect, history)},
                    {"role": "user", "content": text}
                ]
            )
            
            if response.choices:
                translation = response.choices[0].message.content
                await db.add_history(user_id, text)
                
                # Cache the translation
                if not user['context_mode'] or not history:
                    await db.cache_translation(text, dialect, translation)
                
                return translation
        except Exception as e:
            api_error = f"Groq error: {str(e)}"
            logger.error(api_error)

    # All APIs failed - try local dictionary fallback
    logger.error(f"All API attempts failed. Last error: {api_error}")
    logger.info(f"Attempting dictionary fallback for: {text[:50]}...")
    
    match = dictionary_fallback.find_match(text)
    if match:
        await db.add_history(user_id, text)
        return dictionary_fallback.format_translation(text, match)
    
    # No dictionary match found
    return (
        "❌ *Translation Service Unavailable*\n\n"
        "The AI translation service is currently unavailable.\n"
        "Please try again in a few minutes.\n\n"
        f"Error: `{api_error}`"
    )

async def translate_voice(file_path: str, user_id: int):
    """Transcribe and translate audio file using Gemini with Groq Whisper fallback."""
    user = await db.get_user(user_id)
    dialect = user['dialect']
    
    version_fallback = [DEFAULT_MODEL, "gemini-2.0-flash-exp", "gemini-2.5-flash", "gemini-1.5-flash"]
    
    api_error = None
    # 1. Try Gemini first (Best for Darja because of multimodal support)
    for model_ver in version_fallback:
        for i, key in enumerate(GEMINI_API_KEYS):
            if not key: continue
            try:
                client = genai.Client(api_key=key)
                
                # FIXED: path -> file
                sample_file = client.files.upload(file=file_path, config={'display_name': "Voice Message"})
                
                prompt = get_system_prompt(dialect)
                prompt += "\nThis is a voice message. Please transcribe the audio accurately, then provide the full translation."
                
                response = client.models.generate_content(
                    model=model_ver,
                    contents=[prompt, sample_file]
                )
                
                try:
                    client.files.delete(name=sample_file.name)
                except:
                    pass
                
                if response and response.text:
                    return response.text.strip()
                    
            except Exception as e:
                logger.error(f"Voice Gemini Error (Key {i}): {e}")
                api_error = str(e)
                continue

    # 2. Try Groq Whisper Fallback
    if GROQ_API_KEY:
        try:
            logger.info("Attempting Groq Whisper fallback...")
            client = AsyncGroq(api_key=GROQ_API_KEY)
            
            # Groq Whisper requires the file to be opened in binary mode
            with open(file_path, "rb") as audio_file:
                transcription = await client.audio.transcriptions.create(
                    file=(os.path.basename(file_path), audio_file.read()),
                    model="whisper-large-v3",
                    response_format="text"
                )
            
            if transcription.text:
                logger.info(f"Whisper transcription success: {transcription.text[:50]}...")
                # Now translate the transcribed text using Groq
                return await translate_text(transcription.text, user_id)
        except Exception as e:
            api_error = f"Whisper error: {str(e)}"
            logger.error(api_error)

    return f"❌ Voice Translation Failed\n\nError: `{api_error}`"

async def generate_tts_audio(text: str, dialect: str) -> str:
    """Generate TTS audio file for the given text and dialect."""
    try:
        # Determine voice - remove emojis/markdown if present
        clean_text = text.replace('*', '').replace('_', '')
        
        # Select voice based on dialect
        voice = TTS_VOICES.get(dialect, TTS_VOICES['fallback'])
        
        # Create temp file path
        temp_dir = tempfile.gettempdir()
        output_path = os.path.join(temp_dir, f"tts_{datetime.now().timestamp()}.mp3")
        
        # Generate audio using edge-tts
        communicate = edge_tts.Communicate(clean_text, voice)
        await communicate.save(output_path)
        
        logger.info(f"Generated TTS audio: {output_path} (Voice: {voice})")
        return output_path
    except Exception as e:
        logger.error(f"TTS Error: {e}")
        return None

class TranslationQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.processing = False
        self.worker_task = None
        self.stats = {'processed': 0, 'failed': 0, 'in_queue': 0}
    
    async def add_translation(self, text: str, user_id: int, chat_id: int, message_id: int):
        """Add translation task to queue."""
        await self.queue.put({
            'text': text,
            'user_id': user_id,
            'chat_id': chat_id,
            'message_id': message_id,
            'timestamp': datetime.now()
        })
        self.stats['in_queue'] = self.queue.qsize()
        logger.info(f"Translation queued for user {user_id}. Queue size: {self.stats['in_queue']}")
    
    async def process_queue(self, ptb_app: Application):
        """Background worker to process translation queue."""
        while self.processing:
            try:
                task = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                self.stats['in_queue'] = self.queue.qsize()
                
                try:
                    logger.info(f"Processing translation for user {task['user_id']}")
                    result_text = await translate_text(task['text'], task['user_id'])
                    await self.send_translation_result(ptb_app, task, result_text)
                    self.stats['processed'] += 1
                except Exception as e:
                    logger.error(f"Queue processing error: {e}")
                    self.stats['failed'] += 1
                    await self.send_translation_result(
                        ptb_app, task, "❌ Error processing your translation. Please try again."
                    )
                finally:
                    self.queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Queue worker error: {e}")
    
    async def send_translation_result(self, ptb_app: Application, task: dict, result_text: str):
        """Send translation result back to the chat."""
        try:
            chunks = split_message(result_text)
            
            # Create keyboard with Save and Report buttons
            keyboard = [
                [
                    InlineKeyboardButton("⭐ Save", callback_data='save_fav'),
                    InlineKeyboardButton("👎 Report/Correct", callback_data='report_issue')
                ]
            ]
            
            for i, chunk in enumerate(chunks):
                try:
                    if i == 0:
                        await ptb_app.bot.edit_message_text(
                            chat_id=task['chat_id'],
                            message_id=task['message_id'],
                            text=chunk,
                            parse_mode='Markdown',
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                    else:
                        await ptb_app.bot.send_message(
                            chat_id=task['chat_id'],
                            text=chunk,
                            parse_mode='Markdown',
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                except Exception as parse_error:
                    logger.warning(f"Markdown parsing failed: {parse_error}")
                    if i == 0:
                        await ptb_app.bot.edit_message_text(
                            chat_id=task['chat_id'],
                            message_id=task['message_id'],
                            text=chunk,
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                    else:
                        await ptb_app.bot.send_message(
                            chat_id=task['chat_id'],
                            text=chunk,
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
            
            # Generate and send TTS audio
            if not result_text.startswith("❌"):
                try:
                    user = await db.get_user(task['user_id'])
                    dialect = user['dialect']
                    audio_path = await generate_tts_audio(result_text, dialect)
                    
                    if audio_path:
                        with open(audio_path, 'rb') as audio:
                            await ptb_app.bot.send_voice(
                                chat_id=task['chat_id'],
                                voice=audio,
                                caption="🗣️ Audio Pronunciation",
                                reply_to_message_id=task['message_id']
                            )
                        os.remove(audio_path)
                except Exception as tts_error:
                    logger.error(f"TTS Send Error: {tts_error}")
                    
        except Exception as e:
            logger.error(f"Error sending translation result: {e}")
    
    async def start_worker(self, ptb_app: Application):
        if not self.processing:
            self.processing = True
            self.worker_task = asyncio.create_task(self.process_queue(ptb_app))
            logger.info("Translation queue worker started")
    
    async def stop_worker(self):
        self.processing = False
        if self.worker_task:
            await self.worker_task
            logger.info("Translation queue worker stopped")
    
    def get_stats(self):
        return self.stats

# Global Queue instance
translation_queue = TranslationQueue()
