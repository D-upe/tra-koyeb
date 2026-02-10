# DarjaBot - Complete Documentation

## 🇩🇿 Overview
DarjaBot is a sophisticated AI-powered Telegram assistant designed to bridge language gaps in Algeria. It translates between **Algerian Darja (Dialect)**, English, and French, supporting both text, voice, and images. It features a robust architecture with caching, rate limiting, subscription tiers, and community-driven verification.

## ✨ Key Features

### 1. Translation Engine
*   **Multi-Directional:** English/French ↔ Darja.
*   **Context Aware:** Understands nuances (e.g., "I am hungry" vs "Where is the taxi").
*   **Dialect Support:** Specialized modes for:
    *   Standard Darja
    *   Algiers (City)
    *   Oran (West)
    *   Constantine (East)
*   **Audio Pronunciation:** Generates TTS audio for every translation to help with pronunciation.

### 2. Input Methods
*   **📝 Text:** Direct messaging.
*   **🎤 Voice:** Send voice notes; the bot transcribes and translates them.
*   **📸 Image (OCR):** Send photos of menus, signs, or texts. The bot detects text and translates it.
*   **⚡ Inline Mode:** Use `@DarjaBot <text>` in any chat to get instant popup translations.

### 3. Community Verification (Golden Dictionary)
*   **Feedback Loop:** Users can flag incorrect translations using the "👎 Report/Correct" button.
*   **Admin Review:** Admins use `/review` to approve user suggestions.
*   **Verified Priority:** Once approved, the "Verified" translation is stored in the database and **always** takes precedence over AI, ensuring perfect accuracy for common phrases.

### 4. User System
*   **Tiers:**
    *   **Free:** 14 translations/hour.
    *   **Basic:** 50/hour ($4.99).
    *   **Pro:** 200/hour ($9.99).
    *   **Unlimited:** No limits ($19.99).
*   **Whitelist Mode:** Optional "Private Beta" mode where only admins or approved users can access the bot.

### 5. Admin Tools
*   **📢 Broadcast:** Send announcements to all users (`/broadcast`).
*   **📊 Stats:** View cache hit rates and queue performance (`/stats`, `/queue`).
*   **🔐 Access Control:** `/grant`, `/revoke`, `/whitelist` to manage users manually.

---

## 🛠️ Technical Architecture

### Stack
*   **Language:** Python 3.11+
*   **Framework:** `python-telegram-bot` (Async)
*   **AI Models:**
    *   **Primary:** Google Gemini 2.0 Flash (Text & Vision).
    *   **Fallback:** Groq (Llama 3 / Mixtral) & Whisper (Audio).
*   **Database:** Dual-mode (PostgreSQL production / SQLite local fallback).
*   **Server:** ASGI with Uvicorn (Flask used for health checks/webhooks).

### Performance Features
*   **Caching:** Common phrases are stored in DB to save API costs and speed up responses (instant reply).
*   **Async Queue:** Heavy tasks (AI generation) are processed in a background queue to keep the bot responsive.
*   **Rate Limiting:** Sliding window limiter prevents abuse.

---

## 📚 Command Reference

### User Commands
| Command | Description |
| :--- | :--- |
| `/start` | Restart bot & check status |
| `/help` | Usage instructions |
| `/dialect` | Switch region (Algiers, Oran, etc.) |
| `/history` | View last 10 translations |
| `/save` | Bookmark a translation (reply to msg) |
| `/saved` | View bookmarked translations |
| `/packages` | View upgrade options |
| `/subscription` | Check your tier usage |
| `/dictionary` | View offline word list |
| `/cancel` | Cancel pending operations |

### Admin Commands
| Command | Description |
| :--- | :--- |
| `/stats` | View database cache stats |
| `/queue` | View active processing queue |
| `/review` | Review user feedback corrections |
| `/broadcast` | Send message to ALL users |
| `/grant <id> <pkg>` | Give free premium access |
| `/revoke <id>` | Revoke access |
| `/whitelist add/remove` | Manage beta access |

---

## 🚀 Deployment & Requirements

### Dependencies
*   `python-telegram-bot`
*   `google-generativeai`
*   `groq`
*   `psycopg` (or `aiosqlite`)
*   `flask` & `uvicorn`
*   `edge-tts`
*   `ffmpeg` (System requirement for audio)

### Environment Variables
```env
TELEGRAM_TOKEN=...
GEMINI_API_KEYS=["key1", "key2"]
GROQ_API_KEY=...
DATABASE_URL=... (Optional, defaults to local sqlite)
ADMIN_CONTACT=@Username
```

---

## 🔮 Future Roadmap
1.  **Referral System:** Viral growth mechanism.
2.  **Daily Quiz:** Gamified learning.
3.  **Phrasebook:** Categorized common phrases (Travel, Market, Emergency).
