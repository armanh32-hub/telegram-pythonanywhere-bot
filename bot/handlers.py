import json
import os
import random
from datetime import datetime
from bot.clients import bot, BOT_INFO, store
from bot.config import COMMIT_SHA, HF_SPACE_ID, RATE_LIMIT, SYSTEM_PROMPT
from bot.ai import ask_ai
from bot.providers import generate
from bot.helpers import is_allowed, keep_typing, send_reply, should_respond
from bot.history import clear_history
from bot.preferences import get_provider, set_provider
from bot.rate_limit import is_rate_limited

# Verbose console logging for local dev and teaching. Enabled by
# BOT_VERBOSE_LOG=1 (run_local.py sets this automatically). Prints one
# line per inbound/outbound message so kids and teachers can see the
# conversation flow in their terminal while the bot is running.
VERBOSE_LOG = os.environ.get("BOT_VERBOSE_LOG", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _log(message, direction: str, text: str) -> None:
    """Print a one-line trace of a message in verbose mode.

    direction is "in" (user → bot) or "out" (bot → user). Text is
    truncated to 500 characters so long AI replies don't flood the
    terminal. Newlines are collapsed for single-line readability.
    """
    if not VERBOSE_LOG:
        return
    user = message.from_user
    user_name = (
        f"@{user.username}" if user.username else (user.first_name or f"user:{user.id}")
    )
    bot_name = f"@{BOT_INFO.username}"
    snippet = (text or "").replace("\n", " ").replace("\r", " ")
    if len(snippet) > 500:
        snippet = snippet[:500] + "..."
    if direction == "in":
        sender, receiver = user_name, bot_name
    else:
        sender, receiver = bot_name, user_name
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {sender} → {receiver}: {snippet}", flush=True)


@bot.message_handler(commands=["start"], func=is_allowed)
def cmd_start(message):
    bot.send_message(
        message.chat.id,
        "Hello! I'm your AI Math and Pyhsics assistant. Send me a message to get started. I can help you with math problems.\n\nUse /help to see available commands.\n\n Are you ready?",
    )


@bot.message_handler(commands=["help"], func=is_allowed)
def cmd_help(message):
    lines = [
        "/start — welcome message",
        "/help  — show this message",
        "/reset — clear conversation history",
        "/about — about this bot",
        "/joke — tells you a funny joke about math or physics",
        "/quote — tells you a motivational quote about math or physics",
        "/fact — tells you an interesting fact about math or physics",
        "/compliment — tells you a kind compliment",
        "/roast <name/nothing> — tells you a playful roast about math or physics with name you write",
        "/roll — rolls a dice",
        "/remember <text> — remembers what you write",
        "/recall — shows you, what he has remembered",
        "/forget — forgets all notes",
        "/problem <math/physics> — gives you a math or physics problem",
        "/sha   — show the live git commit SHA",
    ]
    if HF_SPACE_ID:
        lines.append("/model — switch AI provider")
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["reset"], func=is_allowed)
def cmd_reset(message):
    clear_history(message.from_user.id)
    bot.send_message(message.chat.id, "Conversation cleared. Starting fresh!")


@bot.message_handler(commands=["about"], func=is_allowed)
def cmd_about(message):
    # Ask the AI to introduce itself, using the configured persona. We call
    # generate() directly (not ask_ai) so this one-off prompt is NOT saved
    # into the user's conversation history. Falls back to a static message if
    # the provider is unavailable so /about never crashes.
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Briefly introduce yourself and what you can help with."},
    ]
    try:
        about_text = generate(message.from_user.id, messages)
    except Exception:
        about_text = (
            "I'm your AI math assistant. Send me a math problem "
            "and I'll explain it step by step."
        )
    bot.send_message(message.chat.id, about_text)

def _one_off(message, system_prompt: str, user_prompt: str) -> None:
    """Send a single AI reply using a per-command system prompt.

    Uses generate() directly instead of ask_ai() so the math-only
    SYSTEM_PROMPT is NOT applied (these fun commands would otherwise be
    refused as off-topic) and the exchange is not saved into the user's
    conversation history. Falls back to a static message if the provider
    is unavailable so the command never crashes silently.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        reply = generate(message.from_user.id, messages)
    except Exception as e:
        print(f"Error in one-off command: {e}")
        reply = "Sorry, I couldn't come up with something right now. Try again!"
    bot.send_message(message.chat.id, reply)


@bot.message_handler(commands=["joke"], func=is_allowed)
def cmd_joke(message):
    _one_off(
        message,
        "You are a witty assistant. Reply with exactly one short, family-friendly joke.",
        "Tell me a funny joke about maths or physics.",
    )

@bot.message_handler(commands=["quote"], func=is_allowed)
def cmd_quote(message):
    _one_off(
        message,
        "You are an inspiring assistant. Reply with one short motivational quote.",
        "Give me a motivational quote about maths or physics.",
    )

@bot.message_handler(commands=["fact"], func=is_allowed)
def cmd_fact(message):
    _one_off(
        message,
        "You are a knowledgeable assistant. Reply with one short, interesting fact.",
        "Tell me an interesting fact about maths or physics.",
    )

@bot.message_handler(commands=["compliment"], func=is_allowed)
def cmd_compliment(message):
    _one_off(
        message,
        "You are a kind, encouraging assistant. Reply with one warm, genuine compliment.",
        "Write a kind compliment for me.",
    )

@bot.message_handler(commands=["roll"], func=is_allowed)
def cmd_roll(message):
    rollNumber = random.randint(1, 6)
    bot.send_message(message.chat.id, f"You rolled a {rollNumber}!")

@bot.message_handler(commands=["roast"], func=is_allowed)
def cmd_roast(message):
    name = message.text.split(maxsplit=1)[1] if " " in message.text else "you"
    _one_off(
        message,
        "You are a playful assistant. Reply with one short, light, friendly roast — never mean.",
        f"Write a short, playful, friendly roast of {name} about math or physics.",
    )

@bot.message_handler(commands=["problem"], func=is_allowed)
def cmd_problem(message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.send_message(message.chat.id, "Please specify the type of problem (math/physics) you would like and its difficulty level.")
        return
    type_of_problem, difficulty = parts[1], parts[2]

    problem = ask_ai(message.chat.id, f"Give me a {type_of_problem} problem with {difficulty} difficulty.")
    bot.send_message(message.chat.id, problem)

@bot.message_handler(commands=["remember"], func=is_allowed)
def cmd_remember(message):
    if store is None:
        bot.send_message(message.chat.id, "Memory isn't available right now.")
        return
    note = message.text.split(maxsplit=1)[1].strip() if " " in message.text else ""
    if not note:
        bot.send_message(message.chat.id, "Usage: /remember <something to remember>")
        return
    key = f"notes:{message.from_user.id}"
    try:
        data = store.get(key)
        notes = json.loads(data) if data else []
        notes.append(note)
        store.set(key, json.dumps(notes))
    except Exception as e:
        print(f"Store error (remember): {e}")
        bot.send_message(message.chat.id, "Couldn't save that. Try again later.")
        return
    bot.send_message(message.chat.id, f"Saved! You now have {len(notes)} note(s).")

@bot.message_handler(commands=["recall"], func=is_allowed)
def cmd_recall(message):
    if store is None:
        bot.send_message(message.chat.id, "Memory isn't available right now.")
        return
    try:
        data = store.get(f"notes:{message.from_user.id}")
        notes = json.loads(data) if data else []
    except Exception as e:
        print(f"Store error (recall): {e}")
        bot.send_message(message.chat.id, "Couldn't read your notes. Try again later.")
        return
    if not notes:
        bot.send_message(
            message.chat.id,
            "I don't have anything saved for you yet. Use /remember <text> first.",
        )
        return
    lines = [f"{i}. {note}" for i, note in enumerate(notes, 1)]
    bot.send_message(message.chat.id, "Here's what you asked me to remember:\n" + "\n".join(lines))

@bot.message_handler(commands=["forget"], func=is_allowed)
def cmd_forget(message):
    if store is None:
        bot.send_message(message.chat.id, "Memory isn't available right now.")
        return
    try:
        store.delete(f"notes:{message.from_user.id}")
    except Exception as e:
        print(f"Store error (forget): {e}")
        bot.send_message(message.chat.id, "Couldn't clear your notes. Try again later.")
        return
    bot.send_message(message.chat.id, "Done — I've forgotten all your notes.")


@bot.message_handler(commands=["sha"], func=is_allowed)
def cmd_sha(message):
    sha = COMMIT_SHA or "unknown"
    bot.send_message(message.chat.id, f"Live SHA: {sha}")


if HF_SPACE_ID:

    @bot.message_handler(commands=["model"], func=is_allowed)
    def cmd_model(message):
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 1:
            current = get_provider(message.from_user.id)
            bot.send_message(
                message.chat.id,
                f"Current provider: {current}\n\n"
                "Options:\n"
                "/model main — Cerebras (fast, multilingual, with memory)\n"
                "/model hf — ArmGPT (Armenian only, slow, no memory)",
            )
            return
        choice = parts[1].strip().lower()
        if choice not in ("main", "hf"):
            bot.send_message(
                message.chat.id, "Invalid choice. Use: /model main or /model hf"
            )
            return
        if not set_provider(message.from_user.id, choice):
            bot.send_message(
                message.chat.id, "Could not save preference. Try again later."
            )
            return
        if choice == "hf":
            bot.send_message(
                message.chat.id,
                "Switched to hf (ArmGPT).\n\n"
                "Note: this is a tiny base completion model trained only on Armenian text. "
                "It will continue whatever you write rather than answer questions, "
                "and it does not understand English. Replies take ~30-60s and there is no memory.",
            )
        else:
            bot.send_message(message.chat.id, "Switched to Main Provider.")


@bot.message_handler(content_types=["text"], func=is_allowed)
def handle_message(message):
    if not should_respond(message):
        return
    text = (message.text or "").replace(f"@{BOT_INFO.username}", "").strip()
    if not text:
        # Edited messages, forwards, or stickers-with-empty-caption can
        # arrive with no usable text. Don't burn rate-limit / AI calls on them.
        return
    _log(message, "in", text)
    if is_rate_limited(message.from_user.id):
        limit_msg = f"You've reached the daily limit of {RATE_LIMIT} messages. Try again tomorrow."
        bot.send_message(message.chat.id, limit_msg)
        _log(message, "out", f"[rate limited] {limit_msg}")
        return
    try:
        with keep_typing(message.chat.id):
            reply = ask_ai(message.from_user.id, text)
        send_reply(message, reply)
        _log(message, "out", reply)
    except Exception as e:
        print(f"Error in handle_message: {e}")
        bot.send_message(message.chat.id, "Something went wrong. Please try again.")
        _log(message, "out", f"[error] {e}")
