def split_message(text, limit=4000):
    """Splits text into chunks to fit Telegram's 4096 character limit."""
    return [text[i:i + limit] for i in range(0, len(text), limit)]

def escape_markdown(text):
    """Escapes special characters for Telegram MarkdownV2."""
    # Since we use simple Markdown (parse_mode=Markdown), we only need to worry about unclosed symbols usually.
    # But strictly for MarkdownV2:
    return text.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[')
