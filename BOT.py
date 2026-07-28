import json
import time
import os
from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

# --- credentials from environment variables (never hardcode in public repos) ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8924274876:AAEAH4zAAluQbdYh2bjY2EUVOlyo4ri3YNs")
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY", "")   # free key at console.groq.com/keys
LOG_URL            = os.environ.get("LOG_URL", "https://raw.githubusercontent.com/22f1000150/TELEGRAM-BOT/main/run.jsonl")
# -------------------------------------------------------------------------------

# Groq — free OpenAI-compatible API, no credit card, 1500 req/day free
client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY,
)
LOG_FILE = "run.jsonl"

# Keeps the last few messages per chat so multi-turn questions work.
conversation_history: dict = {}

def log_event(event: dict) -> None:
    event["timestamp"] = time.time()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id   = update.effective_chat.id
    user_text = update.message.text
    log_event({"type": "incoming", "chat_id": chat_id, "text": user_text})

    history = conversation_history.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})

    system_prompt = (
        "You are a careful data analyst. The user's LAST message asks a data-analysis "
        "question and tells you exactly what JSON shape to reply with. Work out the "
        "real answer (use any public data you know, e.g. MOSPI statistics, general "
        "world knowledge, or arithmetic on numbers given in the message). "
        "Reply with ONLY that exact JSON object and absolutely nothing else — no "
        "explanation, no markdown, no code fences, just the raw JSON."
    )

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system_prompt}] + history[-6:],
        )
        reply_text = response.choices[0].message.content.strip()
    except Exception as api_err:
        err_msg = f"AI API error: {api_err}"
        log_event({"type": "error", "chat_id": chat_id, "error": err_msg})
        await update.message.reply_text(f"Bot error: {err_msg}")
        return

    history.append({"role": "assistant", "content": reply_text})

    # Strip markdown fences if the model wrapped the JSON anyway
    if reply_text.startswith("```"):
        lines = reply_text.splitlines()
        reply_text = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()

    # Parse JSON; if the model added surrounding text, extract the {...} block
    try:
        parsed = json.loads(reply_text)
    except json.JSONDecodeError:
        start = reply_text.find("{")
        end   = reply_text.rfind("}")
        parsed = json.loads(reply_text[start : end + 1])

    # Always inject log_url so the grader can fetch the run log
    parsed["log_url"] = LOG_URL
    final_reply = json.dumps(parsed)

    log_event({"type": "outgoing", "chat_id": chat_id, "text": final_reply})
    await update.message.reply_text(final_reply)

app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
print("Bot is running... (Ctrl+C to stop)")
app.run_polling()

