#!/usr/bin/env python3
"""Quick test script to verify bot setup."""

import os
import sys
from dotenv import load_dotenv

# Load test environment
load_dotenv('.env.test')

def test_setup():
    """Test basic setup."""
    print("🧪 Testing Darja Bot Setup\n")
    
    # Check Python version
    print(f"✅ Python version: {sys.version.split()[0]}")
    
    # Check environment variables
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if token and token != 'your_test_bot_token_here':
        print(f"✅ TELEGRAM_BOT_TOKEN set ({len(token)} chars)")
    else:
        print("❌ TELEGRAM_BOT_TOKEN not configured!")
        print("   Edit .env.test and add your test bot token")
        return False
    
    # Check API keys
    api_key = os.getenv('GEMINI_API_KEY')
    if api_key and api_key != 'your_api_key_here':
        print(f"✅ GEMINI_API_KEY set ({len(api_key)} chars)")
    else:
        print("⚠️  GEMINI_API_KEY not set")
    
    grok_key = os.getenv('GROK_API_KEY')
    if grok_key and grok_key != 'your_grok_api_key_here':
        print(f"✅ GROK_API_KEY set ({len(grok_key)} chars)")
    else:
        print("⚠️  GROK_API_KEY not set")
    
    if not api_key and not grok_key:
        print("❌ No AI API keys configured! Dictionary fallback only.")
    
    # Check database path
    db_path = os.getenv('DATABASE_PATH', 'translations.db')
    print(f"✅ Database path: {db_path}")
    
    # Test imports
    print("\n📦 Testing imports...")
    try:
        import flask
        print("  ✅ Flask")
    except ImportError as e:
        print(f"  ❌ Flask: {e}")
        return False
    
    try:
        import telegram
        print("  ✅ python-telegram-bot")
    except ImportError as e:
        print(f"  ❌ python-telegram-bot: {e}")
        return False
    
    try:
        import google.generativeai
        print("  ✅ google-generativeai")
    except ImportError as e:
        print(f"  ❌ google-generativeai: {e}")
        return False
    
    try:
        import aiosqlite
        print("  ✅ aiosqlite")
    except ImportError as e:
        print(f"  ❌ aiosqlite: {e}")
        return False
    
    try:
        import openai
        print("  ✅ openai (Grok)")
    except ImportError as e:
        print(f"  ❌ openai: {e}")
        return False
    
    print("\n✨ Setup looks good!")
    print("\nNext steps:")
    print("1. Run: ./run_test.sh")
    print("2. Open http://localhost:8080/status in browser")
    print("3. Message your test bot on Telegram")
    return True

if __name__ == '__main__':
    success = test_setup()
    sys.exit(0 if success else 1)
