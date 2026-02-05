#!/bin/bash

echo "🔍 Diagnosing Darja Bot Setup"
echo "=============================="
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found!"
    echo "   Run: python3 -m venv venv"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

echo "✅ Virtual environment activated"

# Check environment file
if [ ! -f ".env.test" ]; then
    echo "❌ .env.test file not found!"
    exit 1
fi

# Load environment
set -a
source .env.test
set +a

echo "✅ Environment loaded"

# Check token
if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ "$TELEGRAM_BOT_TOKEN" = "your_test_bot_token_here" ]; then
    echo "❌ TELEGRAM_BOT_TOKEN not configured!"
    echo "   Edit .env.test and add your bot token from @BotFather"
    exit 1
fi

echo "✅ Bot token configured (${#TELEGRAM_BOT_TOKEN} chars)"

# Test Telegram API connectivity
echo ""
echo "🧪 Testing Telegram API..."
BOT_INFO=$(curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe")

if echo "$BOT_INFO" | grep -q '"ok":true'; then
    BOT_NAME=$(echo "$BOT_INFO" | grep -o '"username":"[^"]*"' | cut -d'"' -f4)
    echo "✅ Telegram API working!"
    echo "   Bot: @$BOT_NAME"
else
    echo "❌ Telegram API error!"
    echo "   Response: $BOT_INFO"
    echo ""
    echo "   Possible issues:"
    echo "   - Invalid bot token"
    echo "   - Network connectivity issues"
    echo "   - Token was revoked"
    exit 1
fi

# Check if bot is already running
echo ""
echo "🧪 Checking if bot is already running..."
if lsof -Pi :8080 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "⚠️  Port 8080 is already in use!"
    echo "   Kill existing process: kill $(lsof -t -i:8080)"
    exit 1
fi

echo "✅ Port 8080 is free"

# Check for existing database
echo ""
echo "🧪 Checking database..."
if [ -f "$DATABASE_PATH" ]; then
    echo "✅ Database exists: $DATABASE_PATH"
    ls -lh "$DATABASE_PATH"
else
    echo "ℹ️  Database will be created on first run: $DATABASE_PATH"
fi

echo ""
echo "🧪 Testing imports..."
python3 << 'PYEOF'
try:
    import flask
    print("✅ Flask imported")
except ImportError as e:
    print(f"❌ Flask import failed: {e}")

try:
    import telegram
    print("✅ python-telegram-bot imported")
except ImportError as e:
    print(f"❌ python-telegram-bot import failed: {e}")

try:
    import google.generativeai
    print("✅ google-generativeai imported")
except ImportError as e:
    print(f"❌ google-generativeai import failed: {e}")

try:
    import aiosqlite
    print("✅ aiosqlite imported")
except ImportError as e:
    print(f"❌ aiosqlite import failed: {e}")

try:
    import uvicorn
    print("✅ uvicorn imported")
except ImportError as e:
    print(f"❌ uvicorn import failed: {e}")
PYEOF

echo ""
echo "=============================="
echo "✅ All checks passed!"
echo ""
echo "You can now start the bot:"
echo "   ./run_test.sh"
echo ""
echo "Then test with:"
echo "   1. Message your bot on Telegram: @${BOT_NAME}"
echo "   2. Send /start"
echo "   3. Check http://localhost:8080/status in your browser"
