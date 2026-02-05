#!/bin/bash
echo "🧪 Quick Bot Test"
echo "=================="
echo ""

# Kill any existing processes on port 8080
lsof -ti:8080 | xargs kill -9 2>/dev/null
sleep 1

# Load environment
set -a
source .env.test
set +a

# Activate venv
source venv/bin/activate

echo "✅ Environment ready"
echo "🤖 Starting bot..."
echo ""
echo "Test in Telegram: @Lang09bot"
echo "Send: /start"
echo ""
echo "(Press Ctrl+C to stop)"
echo ""

# Run bot with timeout for quick test
timeout 30 python app.py 2>&1 | tee bot_test.log &
PID=$!

sleep 5

if grep -q "Bot is now listening" bot_test.log 2>/dev/null; then
    echo "✅ Bot started successfully!"
    echo ""
    echo "Check Telegram now - send /start to @Lang09bot"
else
    echo "⚠️  Checking logs..."
    tail -20 bot_test.log
fi

wait $PID 2>/dev/null
