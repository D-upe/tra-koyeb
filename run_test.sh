#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Starting Darja Bot in TEST mode...${NC}"
echo ""

# Load test environment
set -a
source .env.test
set +a

# Check if venv exists
if [ ! -d "venv" ]; then
    echo -e "${RED}❌ Virtual environment not found!${NC}"
    echo "   Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

echo -e "${GREEN}✅${NC} Virtual environment activated"

# Check token
if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ "$TELEGRAM_BOT_TOKEN" = "your_test_bot_token_here" ]; then
    echo -e "${RED}❌ TELEGRAM_BOT_TOKEN not configured!${NC}"
    echo "   Edit .env.test and add your bot token from @BotFather"
    exit 1
fi

echo -e "${GREEN}✅${NC} Bot token configured (${#TELEGRAM_BOT_TOKEN} chars)"

# Show configuration
echo ""
echo -e "${YELLOW}📊 Configuration:${NC}"
echo "   Database: $DATABASE_PATH"
echo "   API Keys: ${#GEMINI_API_KEY} characters configured"
echo "   Port: $PORT"

if [ -z "$KOYEB_PUBLIC_URL" ]; then
    echo -e "   Mode: ${GREEN}POLLING (local testing)${NC}"
else
    echo -e "   Mode: ${YELLOW}WEBHOOK${NC}"
    echo "   URL: $KOYEB_PUBLIC_URL"
fi

echo ""
echo -e "${YELLOW}🔗 Test URLs:${NC}"
echo "   Health:  http://localhost:$PORT/health"
echo "   Status:  http://localhost:$PORT/status"
echo "   Metrics: http://localhost:$PORT/metrics"
echo ""

# Run the bot with error handling
python app.py 2>&1 | while IFS= read -r line; do
    echo "$line"
    
    # Check for common errors
    if echo "$line" | grep -q "Invalid token"; then
        echo ""
        echo -e "${RED}❌ ERROR: Invalid bot token!${NC}"
        echo "   Get a new token from @BotFather and update .env.test"
        exit 1
    fi
    
    if echo "$line" | grep -q "Conflict: terminated by other getUpdates"; then
        echo ""
        echo -e "${YELLOW}⚠️  WARNING: Another bot instance is running!${NC}"
        echo "   Stop the other instance or use a different bot token"
    fi
    
    if echo "$line" | grep -q "Address already in use"; then
        echo ""
        echo -e "${RED}❌ ERROR: Port $PORT is already in use!${NC}"
        echo "   Kill existing process: kill $(lsof -t -i:$PORT)"
        exit 1
    fi
done
