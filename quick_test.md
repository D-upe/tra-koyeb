# 🧪 Testing Checklist

## Start the Bot
```bash
./run_test.sh
```

You should see:
- "💾 Database connected: ./test_translations.db"
- "Translation queue worker started"
- "Webhook: (none - using polling for local testing)"
- Uvicorn running on http://0.0.0.0:8080

## Test in Browser
Open these URLs while bot is running:
- http://localhost:8080/health - JSON health check
- http://localhost:8080/status - Pretty HTML dashboard  
- http://localhost:8080/metrics - Prometheus metrics

## Test in Telegram

### Basic Commands
1. **Start**: `/start` → Welcome message
2. **Help**: `/help` → Shows all commands with rate limit info

### Core Translation
3. **Translate**: Send "hello" 
   - Should get Darja translation
   - Wait 2-3 seconds (API call)
   
4. **Cache Test**: Send "hello" again
   - Should be instant
   - Should show "⚡ Cached" at top
   
5. **Dictionary**: Send "how are you"
   - Should translate with cultural note

### Database Features
6. **History**: `/history`
   - Should show "hello" and "how are you"
   
7. **Save**: Reply to any message with `/save`
   - Should say "⭐ Translation bookmarked!"
   
8. **View Saved**: `/saved`
   - Should show your bookmarked translation

### Admin Features
9. **Stats**: `/stats`
   - Shows cache hits, entries, hit rate
   - Should show hit_rate > 0% if you did step 4
   
10. **Queue**: `/queue`
    - Shows queue status (should be empty when not busy)
    
11. **Dictionary**: `/dictionary`
    - Shows all available offline words

### Rate Limiting Test
12. **Rate Limit**: Send 11 different messages quickly
    - 11th should show rate limit error
    - Should tell you how many minutes to wait

### Offline Mode Test
13. **Offline**: Temporarily disconnect internet
    - Send "hello" → Should work from dictionary
    - Send "unknown phrase" → Should show fallback message
    - Reconnect internet

## Expected Results

✅ **All translations work**
✅ **Caching is instant on second try**
✅ **History persists after restart**
✅ **Rate limit kicks in at 11th message**
✅ **Status page shows metrics**
✅ **Offline dictionary works**

## Troubleshooting

**"No module named X"**
→ Run: `source venv/bin/activate`

**"Database locked"**
→ Delete test DB: `rm test_translations.db` and restart

**"Invalid token"**
→ Check your bot token in .env.test

**Bot doesn't respond**
→ Check logs in terminal where you ran ./run_test.sh
→ Verify bot token is correct

## Stop Testing
Press `Ctrl+C` in the terminal to stop the bot.

Your test database (`test_translations.db`) will be saved.
Delete it anytime: `rm test_translations.db`
