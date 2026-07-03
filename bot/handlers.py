import io
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
        "/problem <math/physics> <low/middle/high> — gives you a math or physics problem with difficulty you wrote",
        "/convert <in unit> <out unit> — converts units of measurement (for example /convert 60km/h m/s)",
        "/constants — shows you math and physics constants",
        "/plot <function of x> — plots a function, e.g. /plot sin(x) + x/2",
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

@bot.message_handler(commands=["problem"], func=is_allowed)
def cmd_problem(message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.send_message(message.chat.id, "Please specify the type of problem (math/physics) you would like and its difficulty level.")
        return
    type_of_problem, difficulty = parts[1], parts[2]

    problem = ask_ai(message.chat.id, f"Give me a {type_of_problem} problem with {difficulty} difficulty. Dont give any hints and dont give the solution and answer.")
    bot.send_message(message.chat.id, problem)

@bot.message_handler(commands=["convert"], func=is_allowed)
def cmd_convert(message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.send_message(message.chat.id, "You must write down both the initial and final units of measurement.")
    input_unit = parts[1]
    output_unit = parts[2]

    reply = ask_ai(message.chat.id, f"Convert {input_unit} to {output_unit}" )

class MathConstants:
    """Common mathematical constants (all dimensionless).

    Each entry is (symbol, value, short description) so the /constants
    command can print exactly one constant per line.
    """

    CONSTANTS = [
        ("π (pi)", "3.14159265358979", "circle circumference ÷ diameter"),
        ("τ (tau)", "6.28318530717959", "one full turn in radians (2π)"),
        ("e (Euler's number)", "2.71828182845905", "base of the natural logarithm"),
        ("φ (golden ratio)", "1.61803398874989", "(1 + √5) ÷ 2"),
        ("√2 (Pythagoras' constant)", "1.41421356237310", "diagonal of a unit square"),
        ("√3 (Theodorus' constant)", "1.73205080756888", "square root of 3"),
        ("√5", "2.23606797749979", "square root of 5"),
        ("γ (Euler–Mascheroni)", "0.57721566490153", "limit of (harmonic sum − ln n)"),
        ("ln 2", "0.69314718055995", "natural logarithm of 2"),
        ("ln 10", "2.30258509299405", "natural logarithm of 10"),
        ("log₁₀ e", "0.43429448190325", "base-10 logarithm of e"),
        ("ζ(3) (Apéry's constant)", "1.20205690315959", "sum of 1/n³ over n ≥ 1"),
        ("K (Catalan's constant)", "0.91596559417722", "sum of (−1)ⁿ/(2n+1)²"),
        ("δ (Feigenbaum δ)", "4.66920160910299", "period-doubling bifurcation ratio"),
        ("α (Feigenbaum α)", "2.50290787509589", "period-doubling width ratio"),
        ("Ω (omega constant)", "0.56714329040978", "solution of Ω·e^Ω = 1"),
    ]


class PhysicsConstants:
    """Fundamental physical constants in SI units (CODATA values).

    Each entry is (symbol, value with unit, short description) so the
    /constants command can print exactly one constant per line.
    """

    CONSTANTS = [
        ("c (speed of light)", "299792458 m/s", "speed of light in vacuum"),
        ("G (gravitational constant)", "6.67430×10⁻¹¹ m³·kg⁻¹·s⁻²", "Newton's constant of gravitation"),
        ("h (Planck constant)", "6.62607015×10⁻³⁴ J·s", "quantum of action"),
        ("ħ (reduced Planck constant)", "1.054571817×10⁻³⁴ J·s", "h ÷ 2π"),
        ("e (elementary charge)", "1.602176634×10⁻¹⁹ C", "charge of a proton"),
        ("k (Boltzmann constant)", "1.380649×10⁻²³ J/K", "energy per kelvin per particle"),
        ("Nₐ (Avogadro constant)", "6.02214076×10²³ mol⁻¹", "particles per mole"),
        ("R (molar gas constant)", "8.314462618 J·mol⁻¹·K⁻¹", "Nₐ × k"),
        ("σ (Stefan–Boltzmann constant)", "5.670374419×10⁻⁸ W·m⁻²·K⁻⁴", "black-body radiated power"),
        ("ε₀ (vacuum permittivity)", "8.8541878128×10⁻¹² F/m", "electric constant"),
        ("μ₀ (vacuum permeability)", "1.25663706212×10⁻⁶ N·A⁻²", "magnetic constant"),
        ("mₑ (electron mass)", "9.1093837015×10⁻³¹ kg", "rest mass of the electron"),
        ("mₚ (proton mass)", "1.67262192369×10⁻²⁷ kg", "rest mass of the proton"),
        ("mₙ (neutron mass)", "1.67492749804×10⁻²⁷ kg", "rest mass of the neutron"),
        ("α (fine-structure constant)", "7.2973525693×10⁻³ (≈ 1/137)", "strength of electromagnetism"),
        ("R∞ (Rydberg constant)", "10973731.568160 m⁻¹", "hydrogen spectrum scale"),
        ("F (Faraday constant)", "96485.33212 C/mol", "charge per mole of electrons"),
        ("a₀ (Bohr radius)", "5.29177210903×10⁻¹¹ m", "size of the hydrogen atom"),
        ("μB (Bohr magneton)", "9.2740100783×10⁻²⁴ J/T", "electron magnetic-moment scale"),
        ("b (Wien's displacement)", "2.897771955×10⁻³ m·K", "peak black-body wavelength × T"),
        ("g (standard gravity)", "9.80665 m/s²", "standard free-fall acceleration"),
        ("atm (standard atmosphere)", "101325 Pa", "standard sea-level pressure"),
    ]


@bot.message_handler(commands=["constants"], func=is_allowed)
def cmd_constants(message):
    lines_of_constants = []
    lines_of_constants.append("📐 Math constants")
    for symbol, value, description in MathConstants.CONSTANTS:
        lines_of_constants.append(f"{symbol} = {value} — {description}")
    lines_of_constants.append("")
    lines_of_constants.append("🔬 Physics constants")
    for symbol, value, description in PhysicsConstants.CONSTANTS:
        lines_of_constants.append(f"{symbol} = {value} — {description}")
    send_reply(message, "\n".join(lines_of_constants))


# Names the /plot expression is allowed to reference. Anything else (an
# unknown function, or an attribute-access exploit like __class__) is
# rejected before eval() ever runs — this is the security boundary.
_PLOT_ALLOWED_NAMES = {
    "x", "pi", "e", "tau",
    "sin", "cos", "tan", "asin", "acos", "atan",
    "sinh", "cosh", "tanh", "exp", "sqrt", "abs",
    "log", "ln", "log10", "log2", "ceil", "floor", "sign",
}


def _render_plot(expr: str, x_min: float = -10.0, x_max: float = 10.0, points: int = 1000):
    """Render y = f(x) over [x_min, x_max] to a PNG in memory.

    matplotlib/numpy are imported lazily (inside this function, not at
    module top) so that (a) worker boot stays fast and light and (b)
    importing this module for the test suite doesn't require them.

    The expression is evaluated with eval() but sandboxed two ways: the
    builtins are stripped, and every alphabetic token must be a known
    math name (see _PLOT_ALLOWED_NAMES). Raises ValueError with a
    user-friendly message on any bad input.
    """
    import re

    import numpy as np
    import matplotlib
    matplotlib.use("Agg")  # headless backend — no display on the server
    import matplotlib.pyplot as plt

    code = expr.replace("^", "**")  # let students write x^2 for x**2
    if "__" in code:
        raise ValueError("that expression isn't allowed.")
    unknown = sorted({n for n in re.findall(r"[A-Za-z_]+", code) if n not in _PLOT_ALLOWED_NAMES})
    if unknown:
        raise ValueError(
            f"unknown name(s): {', '.join(unknown)}. "
            "Use x and functions like sin, cos, exp, sqrt, log."
        )

    x = np.linspace(x_min, x_max, points)
    namespace = {
        "x": x, "pi": np.pi, "e": np.e, "tau": 2 * np.pi,
        "sin": np.sin, "cos": np.cos, "tan": np.tan,
        "asin": np.arcsin, "acos": np.arccos, "atan": np.arctan,
        "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh,
        "exp": np.exp, "sqrt": np.sqrt, "abs": np.abs,
        "log": np.log, "ln": np.log, "log10": np.log10, "log2": np.log2,
        "ceil": np.ceil, "floor": np.floor, "sign": np.sign,
    }
    try:
        with np.errstate(all="ignore"):  # divide-by-zero / domain errors -> nan, no warning spam
            y = eval(code, {"__builtins__": {}}, namespace)
    except Exception:
        raise ValueError("couldn't understand that function. Example: /plot x**2 - 3*x + 2")

    y = np.asarray(y, dtype=float)
    y = np.full_like(x, float(y)) if y.ndim == 0 else np.broadcast_to(y, x.shape).astype(float)

    # Break the curve across asymptotes (e.g. tan(x), 1/x) so matplotlib
    # doesn't draw near-vertical lines connecting +inf to -inf.
    diffs = np.abs(np.diff(y))
    finite_diffs = diffs[np.isfinite(diffs)]
    if finite_diffs.size:
        jump = max(np.percentile(finite_diffs, 99) * 10, 1e-9)
        y[:-1][diffs > jump] = np.nan

    finite = y[np.isfinite(y)]
    if finite.size == 0:
        raise ValueError(f"the function has no real values on [{x_min:g}, {x_max:g}].")

    fig, ax = plt.subplots(figsize=(8, 5), dpi=110)
    ax.plot(x, y, color="#1f77b4", linewidth=2)
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.axvline(0, color="gray", linewidth=0.8)
    ax.grid(True, alpha=0.3)
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_title(f"y = {expr}")

    # Clip the y-axis to the bulk of the data so a single spike doesn't
    # flatten the interesting part of the curve.
    lo, hi = np.percentile(finite, [2, 98])
    if hi > lo:
        pad = (hi - lo) * 0.15
        ax.set_ylim(lo - pad, hi + pad)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)  # release the figure so repeated calls don't leak memory
    buf.seek(0)
    return buf


@bot.message_handler(commands=["plot"], func=is_allowed)
def cmd_plot(message):
    expr = message.text.split(maxsplit=1)[1].strip() if " " in message.text else ""
    if not expr:
        bot.send_message(
            message.chat.id,
            "Usage: /plot <function of x>\nExample: /plot sin(x) + x/2",
        )
        return
    try:
        image = _render_plot(expr)
    except ValueError as e:
        bot.send_message(message.chat.id, f"Couldn't plot that: {e}")
        return
    except Exception as e:
        print(f"Plot error: {e}")
        bot.send_message(message.chat.id, "Sorry, I couldn't plot that function.")
        return
    bot.send_photo(message.chat.id, image, caption=f"y = {expr}   (x from -10 to 10)")


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
