from flask import Flask, request, session, redirect, url_for, render_template_string
from threading import Thread
import discord
from discord.ext import commands, tasks
import os
import json
import sys
import re
import ast
import time
import asyncio
import operator
import secrets
import traceback
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from word2number import w2n
import random

# Force unbuffered stdout so Render logs show print() output immediately, in order
sys.stdout.reconfigure(line_buffering=True)

# === Keep-Alive Server + Web Dashboard ===
app = Flask('')
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)

@app.route('/')
def home():
    return "Bot is running."

LOGIN_PAGE = """
<!DOCTYPE html><html><head><title>E3N Login</title>
<style>
  body { background:#1e1f22; color:#e3e5e8; font-family:sans-serif; display:flex;
         align-items:center; justify-content:center; height:100vh; margin:0; }
  .box { background:#2b2d31; padding:32px; border-radius:10px; width:280px; text-align:center; }
  input { width:100%; padding:10px; margin-top:12px; border-radius:6px; border:none;
          background:#1e1f22; color:#e3e5e8; box-sizing:border-box; }
  button { width:100%; padding:10px; margin-top:14px; border-radius:6px; border:none;
           background:#5865F2; color:white; font-weight:600; cursor:pointer; }
  .error { color:#f23f42; font-size:13px; margin-top:10px; }
</style></head>
<body>
  <div class="box">
    <h2>🤖 E3N Dashboard</h2>
    <form method="POST">
      <input type="password" name="password" placeholder="Password" autofocus>
      <button type="submit">Log In</button>
    </form>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
  </div>
</body></html>
"""

DASHBOARD_PAGE = """
<!DOCTYPE html><html><head><title>E3N Dashboard</title>
<style>
  body { background:#1e1f22; color:#e3e5e8; font-family:sans-serif; margin:0; padding:24px; }
  .header { display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; }
  h1 { font-size:22px; margin:0; }
  a.logout { color:#f23f42; text-decoration:none; font-size:14px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:16px; margin-bottom:16px; }
  .card { background:#2b2d31; border-radius:10px; padding:18px; }
  .card h2 { font-size:16px; margin:0; color:#b5bac1; }
  .card-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }
  .card-header select { background:#1e1f22; color:#e3e5e8; border:1px solid #3a3c41; border-radius:6px;
                         padding:4px 8px; font-size:13px; cursor:pointer; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th, td { text-align:left; padding:6px 4px; border-bottom:1px solid #3a3c41; }
  th { color:#949ba4; font-weight:600; }
  .online { color:#23a55a; font-weight:600; }
  .offline { color:#f23f42; font-weight:600; }
</style></head>
<body>
  <div class="header">
    <h1>🤖 E3N Dashboard</h1>
    <a class="logout" href="/logout">Log out</a>
  </div>

  <div class="grid">
    <div class="card">
      <h2>Bot Status</h2>
      <table>
        <tr><td>Status</td><td>{% if bot_online %}<span class="online">🟢 Online</span>{% else %}<span class="offline">🔴 Offline</span>{% endif %}</td></tr>
        <tr><td>Logged in as</td><td>{{ bot_user }}</td></tr>
        <tr><td>Servers</td><td>{{ guild_count }}</td></tr>
      </table>
    </div>
    <div class="card">
      <h2>Counting Game</h2>
      <table>
        <tr><td>Current count</td><td>{{ count_data.current_count }}</td></tr>
        <tr><td>Status</td><td>{{ "🟢 On" if count_data.enabled else "🔴 Off" }}</td></tr>
        <tr><td>All-time record</td><td>{{ count_data.best_streak }}{% if count_data.best_streak_holder %} (by {{ count_data.best_streak_holder }}){% endif %}</td></tr>
      </table>
    </div>
    <div class="card">
      <h2>Supabase Stats</h2>
      <table>
        <tr><td>Connection</td><td>{% if db_stats.connected %}<span class="online">🟢 Connected</span>{% else %}<span class="offline">🔴 Disconnected</span>{% endif %}</td></tr>
        <tr><td>Query latency</td><td>{{ db_stats.latency_ms }} ms</td></tr>
        <tr><td>Database size</td><td>{{ db_stats.db_size }}</td></tr>
        <tr><td>Members tracked</td><td>{{ db_stats.members_count }}</td></tr>
        <tr><td>Counters tracked</td><td>{{ db_stats.counters_count }}</td></tr>
      </table>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <div class="card-header">
        <h2>Counting Leaderboard</h2>
        <select id="leaderboardSelect" onchange="switchBoard()">
          <option value="count">🔢 Top Counters</option>
          <option value="ruined">💀 Count Ruiners</option>
        </select>
      </div>
      <table id="countTable">
        <tr><th>#</th><th>Name</th><th>Correct</th><th>Ruined</th></tr>
        {% for u in leaderboard %}
        <tr><td>{{ loop.index }}</td><td>{{ u.display_name }}</td><td>{{ u.total_correct }}</td><td>{{ u.times_ruined }}</td></tr>
        {% else %}
        <tr><td colspan="4">No data yet.</td></tr>
        {% endfor %}
      </table>
      <table id="ruinedTable" style="display:none;">
        <tr><th>#</th><th>Name</th><th>Ruined</th><th>Correct</th></tr>
        {% for u in ruined_leaderboard %}
        <tr><td>{{ loop.index }}</td><td>{{ u.display_name }}</td><td>{{ u.times_ruined }}</td><td>{{ u.total_correct }}</td></tr>
        {% else %}
        <tr><td colspan="4">Nobody's ruined the count yet!</td></tr>
        {% endfor %}
      </table>
    </div>
    <div class="card">
      <h2>Strikes &amp; Hosting ({{ month }})</h2>
      <table>
        <tr><th>Name</th><th>Strikes</th><th>Hosted</th></tr>
        {% for m in members_data.values() %}
        <tr><td>{{ m.display_name }}</td><td>{{ m.strikes }}</td><td>{{ m.monthly.get(month, 0) }}</td></tr>
        {% else %}
        <tr><td colspan="3">No data yet.</td></tr>
        {% endfor %}
      </table>
    </div>
  </div>

  <script>
    function switchBoard() {
      const val = document.getElementById('leaderboardSelect').value;
      document.getElementById('countTable').style.display = val === 'count' ? 'table' : 'none';
      document.getElementById('ruinedTable').style.display = val === 'ruined' ? 'table' : 'none';
    }
  </script>
</body></html>
"""

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        expected = os.getenv("DASHBOARD_PASSWORD")
        if not expected:
            error = "DASHBOARD_PASSWORD isn't set on the server yet."
        elif request.form.get('password') == expected:
            session['authenticated'] = True
            return redirect(url_for('dashboard'))
        else:
            error = "Wrong password."
    return render_template_string(LOGIN_PAGE, error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if not session.get('authenticated'):
        return redirect(url_for('login'))

    # `bot`, `load_data`, `load_count_data`, `get_current_month_key`, and
    # `get_db_stats` are all defined further down in this file — that's fine,
    # Python only looks them up when this function actually runs (i.e. when
    # someone visits the page), by which point the whole file has loaded.
    bot_online = bot.is_ready()
    bot_user = str(bot.user) if bot.user else "Not connected yet"
    guild_count = len(bot.guilds) if bot.is_ready() else 0

    members_data = load_data()
    month = get_current_month_key()
    count_data = load_count_data()
    all_users = count_data.get("users", {}).values()
    leaderboard = sorted(all_users, key=lambda u: u["total_correct"], reverse=True)[:10]
    ruined_leaderboard = sorted(
        (u for u in all_users if u["times_ruined"] > 0),
        key=lambda u: u["times_ruined"], reverse=True
    )[:10]
    db_stats = get_db_stats()

    return render_template_string(
        DASHBOARD_PAGE,
        bot_online=bot_online, bot_user=bot_user, guild_count=guild_count,
        members_data=members_data, month=month,
        count_data=count_data, leaderboard=leaderboard, ruined_leaderboard=ruined_leaderboard,
        db_stats=db_stats
    )

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()

# === Load Token & DB URL ===
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
_raw_db_url = os.getenv("DATABASE_URL")
DATABASE_URL = _raw_db_url.strip() if _raw_db_url else None

# Diagnostic: catches invisible copy-paste issues (trailing space/newline) that
# look identical to the human eye but break the connection every time.
if _raw_db_url and _raw_db_url != DATABASE_URL:
    print(f"⚠️ DATABASE_URL had leading/trailing whitespace that was auto-stripped. "
          f"Raw length={len(_raw_db_url)}, cleaned length={len(DATABASE_URL)}")
elif DATABASE_URL:
    print(f"DATABASE_URL loaded OK, length={len(DATABASE_URL)}, no stray whitespace detected")
else:
    print("⚠️ DATABASE_URL is not set at all")

# === Bot Setup ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Serializes counting-channel message handling so simultaneous messages can't
# both read the same "current count" before either one saves — prevents race
# conditions when multiple people type at nearly the same moment.
counting_lock = asyncio.Lock()

# === Database Setup ===
def get_db():
    # Opens one connection to Supabase. sslmode="require" is needed because
    # Supabase only accepts encrypted connections.
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    # Runs once when the bot starts. Creates every table the bot needs if
    # they don't already exist — safe to run every time, won't wipe data.
    masked = (DATABASE_URL[:40] + "...") if DATABASE_URL else "None"
    print(f"🔌 Connecting to database: {masked}")
    try:
        conn = get_db()
        cur = conn.cursor()
        # Strikes + hosting log data, one row per Discord member
        cur.execute("""
            CREATE TABLE IF NOT EXISTS members (
                user_id TEXT PRIMARY KEY,
                display_name TEXT,
                strikes INT DEFAULT 0,
                monthly JSONB DEFAULT '{}'::jsonb
            )
        """)
        # Counting game settings — only ever one row (id=1), acts like a
        # single save-slot for "what channel, what number are we on, etc."
        cur.execute("""
            CREATE TABLE IF NOT EXISTS counting_config (
                id INT PRIMARY KEY DEFAULT 1,
                channel_id BIGINT,
                enabled BOOLEAN DEFAULT TRUE,
                current_count INT DEFAULT 0,
                last_user_id TEXT,
                best_streak INT DEFAULT 0,
                best_streak_holder TEXT
            )
        """)
        cur.execute("INSERT INTO counting_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
        # Counting leaderboard stats, one row per person who's ever counted
        cur.execute("""
            CREATE TABLE IF NOT EXISTS counting_users (
                user_id TEXT PRIMARY KEY,
                display_name TEXT,
                total_correct INT DEFAULT 0,
                times_ruined INT DEFAULT 0
            )
        """)
        # General bot settings — single-row table like counting_config above.
        # monthly_report_channel_id / last_monthly_reset power the monthly
        # report + reset feature further down.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                id INT PRIMARY KEY DEFAULT 1,
                log_channel_id BIGINT,
                monthly_report_channel_id BIGINT,
                last_monthly_reset TEXT
            )
        """)
        cur.execute("INSERT INTO bot_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
        # Safe to run even on a table that already existed before these
        # columns were added — won't touch anything if they're already there.
        cur.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS monthly_report_channel_id BIGINT")
        cur.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS last_monthly_reset TEXT")
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Database ready")
    except Exception as e:
        print(f"⚠️ Failed to initialize database: {e}")
        traceback.print_exc()

def get_db_stats():
    # Powers the "Supabase Stats" dashboard card — measures how long a quick
    # round-trip query takes, plus overall database size and row counts.
    try:
        start = time.monotonic()
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
        db_size = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM members")
        members_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM counting_users")
        counters_count = cur.fetchone()[0]
        cur.close()
        conn.close()
        latency_ms = round((time.monotonic() - start) * 1000)
        return {
            "connected": True,
            "db_size": db_size,
            "members_count": members_count,
            "counters_count": counters_count,
            "latency_ms": latency_ms,
        }
    except Exception as e:
        print(f"⚠️ Failed to fetch DB stats: {e}")
        return {"connected": False, "db_size": "—", "members_count": 0, "counters_count": 0, "latency_ms": None}

# === Strikes/Hosting Storage (members table) ===
def load_data():
    # Pulls every member's strikes/hosting record out of the database and
    # returns it as one big dict, keyed by their Discord user ID.
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM members")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {
            row["user_id"]: {
                "display_name": row["display_name"],
                "strikes": row["strikes"],
                "monthly": row["monthly"] or {}
            } for row in rows
        }
    except Exception as e:
        print(f"⚠️ Failed to load members: {e}")
        return {}

def save_data(data):
    # Wipes the members table and re-writes it from scratch using whatever
    # is currently in `data`. Simple but effective for a server this size.
    # Returns True/False so commands can tell the user if a save failed.
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM members")
        for uid, rec in data.items():
            cur.execute(
                "INSERT INTO members (user_id, display_name, strikes, monthly) VALUES (%s, %s, %s, %s)",
                (uid, rec["display_name"], rec["strikes"], Json(rec["monthly"]))
            )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"⚠️ Failed to save members: {e}")
        traceback.print_exc()
        return False

def get_current_month_key():
    # Returns something like "2026-08" so hosting counts reset naturally each month.
    now = datetime.utcnow()
    return now.strftime("%Y-%m")

def ensure_member(data, member: discord.Member):
    # Makes sure this Discord member has a record in `data` before we try to
    # edit their strikes/hosting numbers — creates one if it's their first time.
    uid = str(member.id)
    if uid not in data:
        data[uid] = {
            "display_name": member.display_name,
            "strikes": 0,
            "monthly": {}
        }
    else:
        data[uid]["display_name"] = member.display_name

    month = get_current_month_key()
    if month not in data[uid]["monthly"]:
        data[uid]["monthly"][month] = 0

    return uid, month

# === Counting Game Storage (counting_config + counting_users tables) ===
def load_count_data():
    # Pulls the counting game's current state (channel, count, streaks) plus
    # everyone's leaderboard stats, and combines them into one dict to work with.
    default = {
        "channel_id": None,
        "enabled": True,
        "current_count": 0,
        "last_user_id": None,
        "best_streak": 0,
        "best_streak_holder": None,
        "users": {}
    }
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM counting_config WHERE id = 1")
        config = cur.fetchone()
        cur.execute("SELECT * FROM counting_users")
        user_rows = cur.fetchall()
        cur.close()
        conn.close()

        if not config:
            return default

        return {
            "channel_id": config["channel_id"],
            "enabled": config["enabled"],
            "current_count": config["current_count"],
            "last_user_id": config["last_user_id"],
            "best_streak": config["best_streak"],
            "best_streak_holder": config["best_streak_holder"],
            "users": {
                row["user_id"]: {
                    "display_name": row["display_name"],
                    "total_correct": row["total_correct"],
                    "times_ruined": row["times_ruined"]
                } for row in user_rows
            }
        }
    except Exception as e:
        print(f"⚠️ Failed to load counting data: {e}")
        return default

def save_count_data(data):
    # Saves the counting game's state back to the database: updates the single
    # config row, then wipes + re-writes the leaderboard rows from `data["users"]`.
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE counting_config SET
                channel_id = %s, enabled = %s, current_count = %s,
                last_user_id = %s, best_streak = %s, best_streak_holder = %s
            WHERE id = 1
        """, (
            data["channel_id"], data["enabled"], data["current_count"],
            data["last_user_id"], data["best_streak"], data["best_streak_holder"]
        ))

        cur.execute("DELETE FROM counting_users")
        for uid, rec in data["users"].items():
            cur.execute(
                "INSERT INTO counting_users (user_id, display_name, total_correct, times_ruined) VALUES (%s, %s, %s, %s)",
                (uid, rec["display_name"], rec["total_correct"], rec["times_ruined"])
            )

        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"⚠️ Failed to save counting data: {e}")
        traceback.print_exc()
        return False

# === Counting: parse numbers, spelled-out words, and simple math ===
# Only basic arithmetic is allowed — no function calls, names, or attribute
# access — so this can never be used to run arbitrary code.
_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

def _eval_math_node(node):
    # Walks the parsed math expression piece by piece and computes the result,
    # only allowing the operators listed above. This is what makes "500+1"
    # safe to evaluate — unlike Python's built-in eval(), it can't run code.
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPERATORS:
        return _SAFE_OPERATORS[type(node.op)](_eval_math_node(node.left), _eval_math_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPERATORS:
        return _SAFE_OPERATORS[type(node.op)](_eval_math_node(node.operand))
    raise ValueError("Disallowed expression")

def parse_count_attempt(content):
    """Returns an int if the message is a valid count attempt (number, math, or
    spelled-out word), otherwise None so normal chat in the channel is ignored."""
    text = content.strip()
    if not text:
        return None

    # Plain integer, e.g. "501"
    if re.fullmatch(r"-?\d+", text):
        return int(text)

    # Simple math expression, e.g. "500+1", "250*2", "(10+5)/3"
    if re.fullmatch(r"[\d\s+\-*/().]+", text) and re.search(r"[+\-*/]", text):
        try:
            result = _eval_math_node(ast.parse(text, mode="eval").body)
        except Exception:
            return None
        if isinstance(result, (int, float)) and float(result).is_integer():
            return int(result)
        return None

    # Spelled-out number, e.g. "five hundred one", "twenty-one"
    try:
        return w2n.word_to_num(text.lower().replace("-", " "))
    except ValueError:
        return None

# === Bot Settings Storage (bot_settings table) ===
def load_bot_settings():
    # Holds the command-log channel, the monthly-report channel, and which
    # month was last processed by the monthly reset (so it never double-fires).
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM bot_settings WHERE id = 1")
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return {"log_channel_id": None, "monthly_report_channel_id": None, "last_monthly_reset": None}
        return {
            "log_channel_id": row.get("log_channel_id"),
            "monthly_report_channel_id": row.get("monthly_report_channel_id"),
            "last_monthly_reset": row.get("last_monthly_reset"),
        }
    except Exception as e:
        print(f"⚠️ Failed to load bot settings: {e}")
        traceback.print_exc()
        return {"log_channel_id": None, "monthly_report_channel_id": None, "last_monthly_reset": None}

def save_bot_settings(settings):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE bot_settings SET log_channel_id = %s, monthly_report_channel_id = %s, last_monthly_reset = %s WHERE id = 1",
            (settings.get("log_channel_id"), settings.get("monthly_report_channel_id"), settings.get("last_monthly_reset"))
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"⚠️ Failed to save bot settings: {e}")
        traceback.print_exc()
        return False

def ensure_count_user(data, member: discord.Member):
    # Same idea as ensure_member() above, but for the counting leaderboard —
    # gives this person a leaderboard entry if they don't already have one.
    uid = str(member.id)
    if uid not in data["users"]:
        data["users"][uid] = {
            "display_name": member.display_name,
            "total_correct": 0,
            "times_ruined": 0
        }
    else:
        data["users"][uid]["display_name"] = member.display_name
    return uid

# === Monthly Report + Reset ===
def build_monthly_report_embed(members_data, month_key):
    # Builds the "closing the books" summary embed for a given month
    # (e.g. "2026-08") — used by both the automatic and manual report.
    try:
        month_label = datetime.strptime(month_key, "%Y-%m").strftime("%B %Y")
    except ValueError:
        month_label = month_key

    if not members_data:
        description = "No activity recorded this month."
    else:
        host_lines = []
        strike_lines = []
        for record in sorted(members_data.values(), key=lambda x: x.get("display_name", "")):
            name = record["display_name"]
            hosted = record.get("monthly", {}).get(month_key, 0)
            strikes = record.get("strikes", 0)
            host_lines.append(f"{name}: {hosted}")
            strike_lines.append(f"{name}: {strikes}")

        if all(line.endswith(": 0") for line in host_lines + strike_lines):
            description = "No activity recorded this month."
        else:
            description = (
                "**Hosting:**\n" + "\n".join(host_lines) +
                "\n\n**Strikes:**\n" + "\n".join(strike_lines)
            )

    return discord.Embed(
        title=f"🧾 {month_label} Report",
        description=description,
        color=discord.Color.blurple()
    )

async def run_monthly_reset(month_key, channel):
    # Posts the report for `month_key`, then wipes everyone's strikes and
    # hosting numbers back to zero — a full "close the books" for the month.
    # Returns True/False so the caller can tell the user what happened.
    data = load_data()
    embed = build_monthly_report_embed(data, month_key)
    try:
        await channel.send(embed=embed)
    except discord.HTTPException as e:
        print(f"⚠️ Failed to send monthly report: {e}")
        return False

    for rec in data.values():
        rec["strikes"] = 0
        rec["monthly"] = {}

    if not save_data(data):
        return False

    settings = load_bot_settings()
    settings["last_monthly_reset"] = month_key
    save_bot_settings(settings)
    return True

@tasks.loop(hours=24)
async def monthly_report_task():
    # Checks once a day; only actually does anything on the 1st of the month,
    # and only once per month even if the bot restarts multiple times that day.
    now = datetime.utcnow()
    if now.day != 1:
        return

    settings = load_bot_settings()
    channel_id = settings.get("monthly_report_channel_id")
    if not channel_id:
        return

    prev_month_date = now.replace(day=1) - timedelta(days=1)
    prev_month_key = prev_month_date.strftime("%Y-%m")
    if settings.get("last_monthly_reset") == prev_month_key:
        return  # already handled this month

    channel = bot.get_channel(channel_id)
    if not channel:
        print("⚠️ Monthly report channel not found — run !channelsettings to set it again.")
        return

    print(f"📅 Running automatic monthly reset for {prev_month_key}")
    await run_monthly_reset(prev_month_key, channel)

@monthly_report_task.before_loop
async def before_monthly_report_task():
    await bot.wait_until_ready()

# === Events ===
@bot.event
async def on_ready():
    # Fires once the bot has fully connected to Discord. This is also where
    # we register all the slash ("/") commands so they show up in Discord's UI.
    print(f"Bot online as {bot.user}")

    # Render sets RENDER_EXTERNAL_URL automatically for every deployed service —
    # printing it here makes Render's log viewer turn it into a clickable link,
    # same as it does for its own "Available at your primary URL" line.
    site_url = os.getenv("RENDER_EXTERNAL_URL", "https://e3n.onrender.com")
    print(f"📊 Dashboard: {site_url}/dashboard")

    if not monthly_report_task.is_running():
        monthly_report_task.start()

    try:
        # Guild sync FIRST (instant) — copies the currently-registered commands
        # into every server the bot is in, while they're still in the tree
        for guild in bot.guilds:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"Synced {len(synced)} slash command(s) to {guild.name}")

        # THEN clear + sync the global scope so Discord doesn't also show a
        # separate global copy of every command (which caused duplicates)
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
    except Exception as e:
        print(f"Slash command sync failed: {e}")

@bot.after_invoke
async def log_command_usage(ctx):
    # Runs automatically after EVERY command finishes (any command, from
    # anyone) — posts a short summary to the log channel set in !channelsettings.
    # If no log channel has been set, this just quietly does nothing.
    try:
        settings = load_bot_settings()
        channel_id = settings.get("log_channel_id")
        if not channel_id:
            return
        channel = bot.get_channel(channel_id)
        if not channel:
            return

        args_display = " ".join(str(a) for a in ctx.args[2:]) if len(ctx.args) > 2 else ""
        kwargs_display = " ".join(f"{k}={v}" for k, v in ctx.kwargs.items())
        extra = " ".join(filter(None, [args_display, kwargs_display]))

        source_channel = ctx.channel.mention if ctx.guild else "DM"
        msg = f"📝 **{ctx.author}** used `!{ctx.command}`"
        if extra:
            msg += f" `{extra}`"
        msg += f" in {source_channel}"

        await channel.send(msg)
    except Exception as e:
        print(f"⚠️ Failed to log command usage: {e}")

@bot.event
async def on_message(message: discord.Message):
    # This fires on every single message sent anywhere in the server, so it
    # doubles as both the command handler AND the counting game logic.
    # Always let normal command processing happen (! and / prefix commands)
    await bot.process_commands(message)

    if message.author.bot:
        return

    # Quick parse before touching the lock/DB — normal chat never contends for the lock
    content = message.content.strip()
    number = parse_count_attempt(content)
    if number is None:
        return

    # Serialize the whole read -> check -> write cycle so two near-simultaneous
    # messages can never both act on the same stale "current count".
    async with counting_lock:
        count_data = load_count_data()
        channel_id = count_data.get("channel_id")

        # Counting turned off, no channel set, or this message isn't in it
        if not count_data.get("enabled", True) or channel_id is None or message.channel.id != channel_id:
            return

        expected = count_data["current_count"] + 1
        uid = ensure_count_user(count_data, message.author)

        same_user_twice = count_data["last_user_id"] == str(message.author.id)
        wrong_number = number != expected

        if same_user_twice or wrong_number:
            # Break the chain: react X, reset to 0 so next valid number is 1, don't delete the message
            try:
                await message.add_reaction("❌")
            except discord.HTTPException:
                pass
            count_data["users"][uid]["times_ruined"] += 1
            count_data["current_count"] = 0
            count_data["last_user_id"] = None
            save_count_data(count_data)
            reason = "you counted twice in a row" if same_user_twice else f"expected {expected}"
            await message.channel.send(f"❌ Count broken by {message.author.display_name} ({reason}). Starting over — next number is **1**.")
            return

        # Correct count — update the running total, streak record, and this
        # person's leaderboard stats, then save everything back to the database
        try:
            await message.add_reaction("✅")
        except discord.HTTPException:
            pass
        count_data["current_count"] = number
        count_data["last_user_id"] = str(message.author.id)
        count_data["users"][uid]["total_correct"] += 1

        if number > count_data["best_streak"]:
            count_data["best_streak"] = number
            count_data["best_streak_holder"] = message.author.display_name

        save_count_data(count_data)

        # Milestone celebration — every 100 gets extra fanfare
        if number % 100 == 0:
            try:
                await message.add_reaction("🎉")
            except discord.HTTPException:
                pass
            await message.channel.send(
                f"🎉 **{number}** reached by {message.author.mention}! Great work, everyone. Keep it going!"
            )

# === Commands ===
# hybrid_command = works as BOTH "!command" and "/command" from one definition.
# discord.app_commands.describe() controls the text shown under each option in the slash UI.

# --- Hosting log commands (moderator only) ---
@bot.hybrid_command(description="Log hosted event(s) for a member")
@discord.app_commands.describe(member="The member to credit", count="How many events to log (default 1)")
@commands.has_permissions(manage_messages=True)
async def loghost(ctx, member: discord.Member, count: int = 1):
    data = load_data()
    uid, month = ensure_member(data, member)
    data[uid]["monthly"][month] += count
    if not save_data(data):
        await ctx.send("❌ Database error — the log wasn't saved. Check Render logs.")
        return
    await ctx.send(f"📌 Logged {count} hosted event(s) for {data[uid]['display_name']}. This month: {data[uid]['monthly'][month]}")

@bot.hybrid_command(description="Remove hosted-event log(s) for a member")
@discord.app_commands.describe(member="The member to adjust", count="How many events to remove (default 1)")
@commands.has_permissions(manage_messages=True)
async def deletehost(ctx, member: discord.Member, count: int = 1):
    data = load_data()
    uid, month = ensure_member(data, member)
    current_count = data[uid]["monthly"].get(month, 0)
    if current_count > 0:
        removed = min(count, current_count)
        data[uid]["monthly"][month] -= removed
        if not save_data(data):
            await ctx.send("❌ Database error — the change wasn't saved. Check Render logs.")
            return
        await ctx.send(f"🗑️ Removed {removed} hosting log(s) for {data[uid]['display_name']}. Now: {data[uid]['monthly'][month]}")
    else:
        await ctx.send(f"❌ No hosting logs to delete for {data[uid]['display_name']} this month.")

# --- Strike commands (moderator only, plus one everyone can view) ---
@bot.hybrid_command(description="Add strike(s) to a member")
@discord.app_commands.describe(member="The member to strike", count="How many strikes to add (default 1)")
@commands.has_permissions(manage_messages=True)
async def strike(ctx, member: discord.Member, count: int = 1):
    data = load_data()
    uid, _ = ensure_member(data, member)
    data[uid]["strikes"] += count
    if not save_data(data):
        await ctx.send("❌ Database error — the strike wasn't saved. Check Render logs.")
        return
    await ctx.send(f"⚠️ Added {count} strike(s) to {data[uid]['display_name']}. Total: {data[uid]['strikes']}")

@bot.hybrid_command(description="Show everyone's strike totals")
async def strikes(ctx):
    data = load_data()
    if not data:
        await ctx.send("📭 No strike data recorded.")
        return

    out = "\n".join(f"{d['display_name']}: {d['strikes']}" for d in data.values())
    await ctx.send("**Strikes:**\n" + out)

@bot.hybrid_command(description="Reset a member's strikes to 0")
@discord.app_commands.describe(member="The member to reset")
@commands.has_permissions(manage_messages=True)
async def resetstrikes(ctx, member: discord.Member):
    data = load_data()
    uid, _ = ensure_member(data, member)
    data[uid]["strikes"] = 0
    if not save_data(data):
        await ctx.send("❌ Database error — the reset wasn't saved. Check Render logs.")
        return
    await ctx.send(f"✅ Strikes reset for {data[uid]['display_name']}.")

@bot.hybrid_command(description="Show this month's hosting + strike totals")
async def logs(ctx):
    data = load_data()
    if not data:
        await ctx.send("📭 No data recorded.")
        return

    month = get_current_month_key()
    host_lines = []
    strike_lines = []

    for record in sorted(data.values(), key=lambda x: x.get("display_name", "")):
        name = record["display_name"]
        hosted = record.get("monthly", {}).get(month, 0)
        strikes = record.get("strikes", 0)
        host_lines.append(f"{name}: {hosted}")
        strike_lines.append(f"{name}: {strikes}")

    if all(line.endswith(": 0") for line in host_lines + strike_lines):
        await ctx.send("🫥 No logs this month.")
        return

    await ctx.send(f"🧾 **{datetime.utcnow().strftime('%B')} Logs**\n\n"
                   f"**Hosting:**\n" + "\n".join(host_lines) +
                   f"\n\n**Strikes:**\n" + "\n".join(strike_lines))

# --- Info-lookup commands (open to everyone) ---
@bot.hybrid_command(description="Show info about a server member")
@discord.app_commands.describe(member="The member to look up (defaults to you)")
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author

    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    roles.reverse()  # highest role first
    roles_display = ", ".join(roles) if roles else "None"
    if len(roles_display) > 1000:
        roles_display = f"{len(roles)} roles (too many to list)"

    embed = discord.Embed(
        title=f"👤 {member.display_name}",
        color=member.color if member.color.value else discord.Color.blurple()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Username", value=str(member), inline=True)
    embed.add_field(name="ID", value=str(member.id), inline=True)
    embed.add_field(name="Bot?", value="Yes" if member.bot else "No", inline=True)
    embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, style="R"), inline=True)
    embed.add_field(name="Joined server", value=discord.utils.format_dt(member.joined_at, style="R") if member.joined_at else "Unknown", inline=True)
    embed.add_field(name="Top role", value=member.top_role.mention if member.top_role.name != "@everyone" else "None", inline=True)
    embed.add_field(name=f"Roles ({len(roles)})", value=roles_display, inline=False)
    await ctx.send(embed=embed)

@bot.hybrid_command(description="Show info about a role")
@discord.app_commands.describe(role="The role to look up")
async def roleinfo(ctx, role: discord.Role):
    embed = discord.Embed(
        title=f"🏷️ {role.name}",
        color=role.color if role.color.value else discord.Color.light_grey()
    )
    embed.add_field(name="ID", value=str(role.id), inline=True)
    embed.add_field(name="Color", value=str(role.color) if role.color.value else "Default", inline=True)
    embed.add_field(name="Members", value=str(len(role.members)), inline=True)
    embed.add_field(name="Position", value=str(role.position), inline=True)
    embed.add_field(name="Mentionable", value="Yes" if role.mentionable else "No", inline=True)
    embed.add_field(name="Shown separately", value="Yes" if role.hoist else "No", inline=True)
    embed.add_field(name="Created", value=discord.utils.format_dt(role.created_at, style="R"), inline=True)
    await ctx.send(embed=embed)

# --- Admin/owner settings commands ---
@bot.hybrid_command(description="Set up all the bot's channels in one guided walkthrough (server owner only)")
async def channelsettings(ctx):
    if ctx.guild is None or ctx.author.id != ctx.guild.owner_id:
        await ctx.send("🚫 Only the server owner can use this command.")
        return

    def check(m):
        return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

    await ctx.send(
        "⚙️ **Channel Setup** — I'll ask about a few channels, one at a time.\n"
        "Mention a channel (like #general) to set it, type `skip` to leave it as-is, "
        "or `cancel` anytime to stop."
    )

    questions = [
        ("log_channel_id", "1️⃣ Where should **command usage logs** be sent?"),
        ("count_channel_id", "2️⃣ Which channel should the **counting game** use? *(Setting this resets the current count to 0.)*"),
        ("monthly_report_channel_id", "3️⃣ Where should **monthly hosting/strike reports** be sent?"),
    ]

    results = {}
    for key, question in questions:
        await ctx.send(question)
        while True:
            try:
                reply = await bot.wait_for("message", check=check, timeout=60)
            except asyncio.TimeoutError:
                await ctx.send("⏳ Setup timed out. Run `!channelsettings` again anytime.")
                return

            text = reply.content.strip().lower()
            if text == "cancel":
                await ctx.send("❌ Setup cancelled. Nothing was changed.")
                return
            if text == "skip":
                results[key] = None  # None means "leave unchanged"
                break
            if reply.channel_mentions:
                results[key] = reply.channel_mentions[0].id
                break
            await ctx.send("❌ That doesn't look like a channel mention. Try again, or type `skip`.")

    settings = load_bot_settings()
    count_data = load_count_data()
    summary_lines = []

    if results["log_channel_id"] is not None:
        settings["log_channel_id"] = results["log_channel_id"]
        summary_lines.append(f"📝 Command logs → <#{results['log_channel_id']}>")
    else:
        summary_lines.append("📝 Command logs → unchanged")

    if results["count_channel_id"] is not None:
        count_data["channel_id"] = results["count_channel_id"]
        count_data["current_count"] = 0
        count_data["last_user_id"] = None
        summary_lines.append(f"🔢 Counting game → <#{results['count_channel_id']}> (count reset to 0)")
    else:
        summary_lines.append("🔢 Counting game → unchanged")

    if results["monthly_report_channel_id"] is not None:
        settings["monthly_report_channel_id"] = results["monthly_report_channel_id"]
        summary_lines.append(f"🧾 Monthly reports → <#{results['monthly_report_channel_id']}>")
    else:
        summary_lines.append("🧾 Monthly reports → unchanged")

    ok1 = save_bot_settings(settings)
    ok2 = save_count_data(count_data)
    if not (ok1 and ok2):
        await ctx.send("❌ Database error while saving one or more settings. Check Render logs.")
        return

    embed = discord.Embed(
        title="✅ Channel Setup Complete",
        description="\n".join(summary_lines),
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

@bot.hybrid_command(description="Post + reset this month's hosting and strikes right now (server owner only)")
async def exportmonth(ctx):
    if ctx.guild is None or ctx.author.id != ctx.guild.owner_id:
        await ctx.send("🚫 Only the server owner can use this command.")
        return

    settings = load_bot_settings()
    channel_id = settings.get("monthly_report_channel_id")
    if not channel_id:
        await ctx.send("❌ No monthly report channel is set yet. Run `!channelsettings` first.")
        return
    channel = bot.get_channel(channel_id)
    if not channel:
        await ctx.send("❌ Couldn't find that channel anymore. Run `!channelsettings` to set it again.")
        return

    month_key = get_current_month_key()
    await ctx.send(f"⏳ Posting this month's report to {channel.mention} and resetting hosting + strikes...")
    success = await run_monthly_reset(month_key, channel)
    if success:
        await ctx.send(f"✅ Done — report posted to {channel.mention}, hosting and strikes reset for everyone.")
    else:
        await ctx.send("❌ Something went wrong. Check Render logs.")

@bot.hybrid_command(description="Turn the counting game on or off")
@discord.app_commands.describe(state="Turn counting on or off")
@discord.app_commands.choices(state=[
    discord.app_commands.Choice(name="on", value="on"),
    discord.app_commands.Choice(name="off", value="off"),
])
@commands.has_permissions(administrator=True)
async def counting(ctx, state: str):
    count_data = load_count_data()

    if state.lower() not in ("on", "off"):
        await ctx.send("❌ Use `!counting on` or `!counting off`.")
        return

    count_data["enabled"] = (state.lower() == "on")
    save_count_data(count_data)

    if count_data["enabled"]:
        await ctx.send("✅ Counting game turned **on**.")
    else:
        await ctx.send("🛑 Counting game turned **off**. Leaderboard and progress are kept.")

# --- Leaderboard display + its reset button ---
def build_leaderboard_embed(count_data):
    # Builds the top-10 leaderboard embed. Pulled into its own function since
    # both !countboard and the reset button below need to redraw this same embed.
    users = count_data.get("users", {})
    ranked = sorted(users.values(), key=lambda u: u["total_correct"], reverse=True)
    lines = [f"{i+1}. {u['display_name']} — {u['total_correct']} correct, {u['times_ruined']} ruined"
              for i, u in enumerate(ranked[:10])] if ranked else ["No counting data yet."]

    embed = discord.Embed(
        title="🔢 Counting Leaderboard",
        description="\n".join(lines),
        color=discord.Color.gold()
    )
    if count_data.get("best_streak_holder"):
        embed.set_footer(text=f"All-time record: {count_data['best_streak']} (by {count_data['best_streak_holder']})")
    return embed

# A "View" is Discord's term for a message with clickable buttons attached.
# This one adds the red "Reset Leaderboard" button under !countboard's embed.
class LeaderboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Reset Leaderboard", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def reset_leaderboard(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("🚫 Only admins can reset the leaderboard.", ephemeral=True)
            return

        count_data = load_count_data()
        count_data["users"] = {}
        count_data["best_streak"] = 0
        count_data["best_streak_holder"] = None
        save_count_data(count_data)

        button.disabled = True
        button.label = "Leaderboard Reset"
        await interaction.response.edit_message(embed=build_leaderboard_embed(count_data), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

@bot.hybrid_command(description="Show the counting game leaderboard")
async def countboard(ctx):
    count_data = load_count_data()
    await ctx.send(embed=build_leaderboard_embed(count_data), view=LeaderboardView())

@bot.hybrid_command(description="Show who's broken the count the most")
async def ruinedboard(ctx):
    count_data = load_count_data()
    users = count_data.get("users", {})

    # Only show people who've actually ruined the count at least once
    ranked = sorted(
        (u for u in users.values() if u["times_ruined"] > 0),
        key=lambda u: u["times_ruined"],
        reverse=True
    )
    lines = [f"{i+1}. {u['display_name']} — {u['times_ruined']} ruined, {u['total_correct']} correct"
              for i, u in enumerate(ranked[:10])] if ranked else ["Nobody's ruined the count yet — clean streak!"]

    embed = discord.Embed(
        title="💀 Count Ruiners Leaderboard",
        description="\n".join(lines),
        color=discord.Color.red()
    )
    await ctx.send(embed=embed)

@bot.hybrid_command(name="commands", description="Show everything E3N can do")
async def commands_list(ctx):
    embed = discord.Embed(
        title="🤖 E3N Commands",
        description="Here's everything I can do:",
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="📋 Everyone",
        value=(
            "`!strikes` — Show everyone's strike totals\n"
            "`!logs` — Show this month's hosting + strike totals\n"
            "`!countboard` — Show the counting game leaderboard\n"
            "`!ruinedboard` — Show who's broken the count the most\n"
            "`!userinfo [@member]` — Show info about a member (defaults to you)\n"
            "`!roleinfo @role` — Show info about a role\n"
            "`!commands` — Show this message"
        ),
        inline=False
    )
    embed.add_field(
        name="🔧 Moderator Only (requires Manage Messages)",
        value=(
            "`!loghost @member [count]` — Log hosted event(s) for a member (default 1)\n"
            "`!deletehost @member [count]` — Remove hosted-event log(s) for a member (default 1)\n"
            "`!strike @member [count]` — Add strike(s) to a member (default 1)\n"
            "`!resetstrikes @member` — Reset a member's strikes to 0"
        ),
        inline=False
    )
    embed.add_field(
        name="🛡️ Admin Only (requires Administrator)",
        value="`!counting on/off` — Turn the counting game on or off",
        inline=False
    )
    embed.add_field(
        name="👑 Server Owner Only",
        value=(
            "`!channelsettings` — Guided setup for all the bot's channels (log, counting, monthly reports)\n"
            "`!exportmonth` — Post + reset this month's hosting and strikes right now"
        ),
        inline=False
    )
    embed.set_footer(text="Works as ! commands or / slash commands")
    await ctx.send(embed=embed)

# === Error Handling ===
# Catches common command mistakes and replies with a friendly message instead
# of letting the bot crash or silently do nothing.
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🚫 You don't have permission to use that command.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ I couldn't find that member.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: `{error.param.name}`")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        raise error

# === Run Bot ===
# Create the database tables (if they don't exist yet), then connect to Discord.
# This is the very last thing that runs — everything above is just definitions.
init_db()
bot.run(TOKEN)