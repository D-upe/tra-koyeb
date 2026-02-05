# Testing Guide for Darja Bot

## Option 1: Test Locally First (Recommended)

### 1. Create Test Environment File
Create `.env.test` file:
```bash
# Test Bot (create a separate test bot via @BotFather)
TELEGRAM_BOT_TOKEN=your_test_bot_token_here

# Same API keys (or use test keys)
GEMINI_API_KEY=your_api_key
GEMINI_API_KEY_2=your_backup_key
GEMINI_API_KEY_3=your_third_key

# Local testing
DATABASE_PATH=./test_translations.db
PORT=8080

# No webhook for local testing (uses polling)
# KOYEB_PUBLIC_URL=
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run Local Tests
```bash
# Terminal 1: Run the bot locally
export $(cat .env.test | xargs)
python app.py

# The bot will start on http://localhost:8080
```

### 4. Test Features
Send these messages to your test bot:

**Basic Tests:**
- `/start` - Welcome message
- `/help` - Commands list
- `hello` - Translation with caching
- `hello` again - Should show "⚡ Cached"

**Database Tests:**
- `/history` - Should show your translation
- `how are you` - Another translation
- `/history` - Should show both
- `/save` (reply to a message) - Bookmark it
- `/saved` - View bookmarks

**Rate Limiting Test:**
- Send 14 translations quickly
- 15th should show rate limit message

**Offline Dictionary Test:**
- Disconnect internet temporarily
- `hello` - Should work with offline dictionary
- `random phrase not in dict` - Should show fallback message

**Admin Commands:**
- `/stats` - Cache statistics
- `/queue` - Queue status
- `/dictionary` - Available offline words

---

## Option 2: Test on Koyeb (Staging Environment)

### 1. Create Separate Koyeb Service
```bash
# Deploy as a new service (different name)
koyeb service create darja-bot-staging \
  --git github.com/yourusername/darja-bot \
  --git-branch main \
  --ports 8080:http \
  --routes /:8080
```

### 2. Use Different Bot Token
Set environment variables for staging:
- `TELEGRAM_BOT_TOKEN` = Test bot token (different from production)
- `DATABASE_PATH` = `/tmp/staging.db` (separate DB)
- `KOYEB_PUBLIC_URL` = Staging URL

### 3. Test Endpoints
Once deployed:
- `https://darja-bot-staging-yourorg.koyeb.app/health`
- `https://darja-bot-staging-yourorg.koyeb.app/status`
- `https://darja-bot-staging-yourorg.koyeb.app/metrics`

---

## Option 3: Quick Production Test (Low Risk)

Since your production bot is running, you can test safely:

### 1. Test Read-Only Commands First
These won't affect production:
- `/help` - Shows new commands
- `/stats` - View cache stats
- `/queue` - View queue status
- `/dictionary` - View offline words
- `/history` - View your personal history
- `/saved` - View your bookmarks

### 2. Test Non-Disruptive Features
- **Caching**: Send "hello" twice - second should be cached
- **Rate limiting**: Try 14+ messages (won't break anything)
- **Dictionary**: If APIs fail, dictionary kicks in

### 3. Monitor During Testing
```bash
# Watch logs
koyeb logs -a darja-bot

# Check health
curl https://your-bot.koyeb.app/health
```

---

## Feature Test Checklist

### ✅ Database Persistence
```
1. Send: "test message"
2. Check /history - should appear
3. Restart bot (or wait a bit)
4. Check /history again - should still be there
```

### ✅ Translation Caching
```
1. Send: "good morning"
2. Wait for translation
3. Send: "good morning" again
4. Should show "⚡ Cached" instantly
5. Check /stats - cache_hits should be > 0
```

### ✅ Rate Limiting
```
1. Send 14 different messages quickly
2. 15th message should show rate limit warning
3. Check remaining time in message
```

### ✅ Async Queue
```
1. Send 3-4 messages rapidly
2. Check response - should show queue positions
3. Check /queue - should show pending items
4. All should process sequentially
```

### ✅ Offline Dictionary
```
# Temporarily break API (or just test the feature)
1. Send: "hello"
2. If API fails, should get offline translation
3. Notice "⚠️ Using offline dictionary"
4. Check /dictionary - see available words
```

### ✅ Health Monitoring
```bash
# Test endpoints
curl https://your-bot.koyeb.app/health
curl https://your-bot.koyeb.app/status
curl https://your-bot.koyeb.app/metrics

# Should return JSON/HTML/Prometheus format respectively
```

---

## Safe Testing Tips

### 1. **Use Different Database**
Set `DATABASE_PATH=/tmp/test.db` in environment to avoid mixing data.

### 2. **Use Test Bot Token**
Create a separate bot with @BotFather for testing.

### 3. **Check Logs**
```bash
# Watch for errors
koyeb logs -a darja-bot --tail 100

# Or if running locally
tail -f app.log
```

### 4. **Database Reset (if needed)**
```bash
# SSH into Koyeb instance or run locally
rm translations.db  # Deletes all data
# Restart bot - will recreate with fresh schema
```

### 5. **Feature Flags**
Add to `.env` to disable features during testing:
```bash
# Disable rate limiting for load testing
DISABLE_RATE_LIMIT=true

# Disable cache to test API fallback
DISABLE_CACHE=true
```

---

## Testing Webhook Integration

### 1. Verify Webhook is Set
```bash
curl https://api.telegram.org/bot<YOUR_TOKEN>/getWebhookInfo
```

### 2. Test Webhook Endpoint
```bash
curl -X POST https://your-bot.koyeb.app/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "update_id": 123456789,
    "message": {
      "message_id": 1,
      "from": {"id": 123, "is_bot": false, "first_name": "Test"},
      "chat": {"id": 123, "type": "private"},
      "date": 1234567890,
      "text": "hello"
    }
  }'
```

Should return "OK".

---

## Performance Testing

### 1. Queue Load Test
```bash
# Send multiple requests rapidly
for i in {1..20}; do
  curl -X POST https://your-bot.koyeb.app/webhook \
    -H "Content-Type: application/json" \
    -d "{...test message $i...}" &
done
wait

# Check /queue to see all are being processed
```

### 2. Monitor Response Times
```bash
# Time the health endpoint
time curl https://your-bot.koyeb.app/health

# Should be < 100ms
```

---

## Troubleshooting

### Issue: "Database locked"
**Solution**: SQLite doesn't handle concurrent writes well. The queue processes sequentially to avoid this. If testing locally with multiple processes, use PostgreSQL instead.

### Issue: "Rate limit not working"
**Solution**: Rate limits are per-user. Testing with same user? That's correct behavior. Try different user IDs.

### Issue: "Cache not hitting"
**Solution**: Cache only works when context_mode is False. Check user settings or disable context mode.

### Issue: "Queue not processing"
**Solution**: Check logs. Worker might not have started. Verify `translation_queue.start_worker()` was called.

---

## Summary

**Safest approach**: Test locally with a test bot token first.

**For production**: Read-only commands (`/stats`, `/queue`, `/dictionary`) are 100% safe.

**For full testing**: Deploy to separate Koyeb staging service with different bot token.

**Monitor**: Use `/health`, `/status`, and `/metrics` endpoints to verify everything works!