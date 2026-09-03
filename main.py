from flask import Flask, request, session, redirect, url_for, render_template_string
from threading import Thread
import discord
from discord.ext import commands, tasks
import os
import json
import sys
import re
import ast
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

# === Keep-Alive Server + Dashboard ===
app = Flask('')
# Random each time the bot restarts — this just signs the login cookie, it
# doesn't need to be remembered, but it does mean everyone gets logged out
# of the dashboard whenever the bot redeploys/restarts.
app.secret_key = secrets.token_hex(32)

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD")

# Recorded the moment this process starts, so the dashboard can show how long
# the current deployment has been alive (resets whenever Render restarts it).
BOT_START_TIME = datetime.utcnow()

def format_uptime(delta: timedelta) -> str:
    # Turns a timedelta into a friendly "X days, Y hours" string for the dashboard.
    total_hours = int(delta.total_seconds() // 3600)
    days, hours = divmod(total_hours, 24)
    if days:
        return f"{days}d {hours}h"
    return f"{hours}h"

@app.route('/')
def home():
    return "Bot is running."

LOGIN_PAGE = """
<!DOCTYPE html>
<html><head><title>E3N Dashboard - Login</title>
<style>
  body { background:#1e1f22; color:#e3e5e8; font-family:-apple-system,sans-serif;
         display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }
  .box { background:#2b2d31; padding:32px; border-radius:12px; width:280px; text-align:center; }
  h1 { font-size:20px; margin-bottom:20px; }
  input { width:100%; padding:10px; border-radius:6px; border:none; margin-bottom:12px;
          background:#1e1f22; color:#e3e5e8; box-sizing:border-box; }
  button { width:100%; padding:10px; border-radius:6px; border:none; background:#5865f2;
           color:white; font-weight:600; cursor:pointer; }
  button:hover { background:#4752c4; }
  .error { color:#f23f42; margin-bottom:12px; font-size:14px; }
</style></head>
<body>
  <div class="box">
    <h1>🤖 E3N Dashboard</h1>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
    <form method="POST">
      <input type="password" name="password" placeholder="Password" autofocus>
      <button type="submit">Log In</button>
    </form>
  </div>
</body></html>
"""

DASHBOARD_PAGE = """
<!DOCTYPE html>
<html><head><title>E3N Dashboard</title>
<style>
  body { background:#1e1f22; color:#e3e5e8; font-family:-apple-system,sans-serif; margin:0; padding:24px; }
  .header { display:flex; justify-content:space-between; align-items:center; margin-bottom:24px; }
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
    <a class="logout" href="{{ url_for('logout') }}">Log out</a>
  </div>

  <div class="grid">
    <div class="card">
      <h2>Bot Status</h2>
      <p>Status: <span class="{{ 'online' if bot_online else 'offline' }}">{{ 'Online' if bot_online else 'Offline' }}</span></p>
      <p>Logged in as: {{ bot_user }}</p>
      <p>Servers: {{ guild_count }}</p>
      <p>Uptime: {{ uptime_display }}</p>
    </div>
    <div class="card">
      <h2>Counting Game</h2>
      <p>Current count: <strong>{{ count_data.current_count }}</strong></p>
      <p>Channel set: {{ 'Yes' if count_data.channel_id else 'No' }}</p>
      <p>Enabled: {{ 'Yes' if count_data.enabled else 'No' }}</p>
      <p>All-time record: {{ count_data.best_streak }}{% if count_data.best_streak_holder %} (by {{ count_data.best_streak_holder }}){% endif %}</p>
    </div>
    <div class="card">
      <h2>Database (Supabase)</h2>
      {% if db_stats.error %}
      <p style="color:#f23f42;">⚠️ {{ db_stats.error }}</p>
      {% else %}
      <p>Database size: <strong>{{ db_stats.db_size }}</strong></p>
      <p>Active connections: <strong>{{ db_stats.active_connections }}</strong></p>
      <p>Total rows tracked: <strong>{{ db_stats.total_rows }}</strong></p>
      <p style="color:#949ba4; font-size:12px;">{{ db_stats.pg_version }}</p>
      {% endif %}
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
    if not DASHBOARD_PASSWORD:
        return "⚠️ DASHBOARD_PASSWORD isn't set in Render's environment variables yet.", 503

    error = None
    if request.method == 'POST':
        if request.form.get('password') == DASHBOARD_PASSWORD:
            session['authenticated'] = True
            return redirect(url_for('dashboard'))
        error = "Incorrect password."
    return render_template_string(LOGIN_PAGE, error=error)

@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if not session.get('authenticated'):
        return redirect(url_for('login'))

    # `bot`, `load_data`, `load_count_data`, and `get_current_month_key` are all
    # defined further down in this file — that's fine, Python only looks them up
    # when this function actually runs (i.e. when someone visits the page),
    # by which point the whole file has already finished loading.
    bot_online = bot.is_ready()
    bot_user = str(bot.user) if bot.user else "Not connected yet"
    guild_count = len(bot.guilds) if bot.is_ready() else 0
    uptime_display = format_uptime(datetime.utcnow() - BOT_START_TIME)

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
        uptime_display=uptime_display,
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
        # General bot settings — right now just the command-log channel.
        # Also a single-row table like counting_config above.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                id INT PRIMARY KEY DEFAULT 1,
                log_channel_id BIGINT
            )
        """)
        cur.execute("INSERT INTO bot_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
        # Added later — safe to run even on an existing table/database
        cur.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS report_channel_id BIGINT")
        cur.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS last_report_month TEXT")
        # Added for the AFK toggle command — stores which role gets applied
        cur.execute("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS afk_role_id BIGINT")
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Database ready")
    except Exception as e:
        print(f"⚠️ Failed to initialize database: {e}")
        traceback.print_exc()

def get_db_stats():
    # Pulls a few read-only stats straight from Postgres itself (not our own
    # tables) — this works because Supabase is just managed Postgres under
    # the hood, so any standard Postgres system view works here too.
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
        db_size = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
        active_connections = cur.fetchone()[0]

        cur.execute("SELECT version()")
        pg_version = cur.fetchone()[0].split(",")[0]

        total_rows = 0
        for table in ("members", "counting_users", "counting_config", "bot_settings"):
            cur.execute(f"SELECT count(*) FROM {table}")
            total_rows += cur.fetchone()[0]

        cur.close()
        conn.close()
        return {
            "db_size": db_size,
            "active_connections": active_connections,
            "pg_version": pg_version,
            "total_rows": total_rows,
        }
    except Exception as e:
        print(f"⚠️ Failed to load database stats: {e}")
        return {"error": str(e)}

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

def get_previous_month_key():
    # First day of this month, minus one day, lands in the previous month —
    # a reliable way to get "last month" regardless of how many days it had.
    first_of_this_month = datetime.utcnow().replace(day=1)
    last_day_prev_month = first_of_this_month - timedelta(days=1)
    return last_day_prev_month.strftime("%Y-%m")

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

def build_month_report_embed(data, month_key, title_prefix="🧾"):
    # Builds the hosting+strikes report embed for one specific month — shared
    # by the manual !exportmonth command and the automatic end-of-month job.
    host_lines = []
    strike_lines = []
    for record in sorted(data.values(), key=lambda x: x.get("display_name", "")):
        name = record["display_name"]
        hosted = record.get("monthly", {}).get(month_key, 0)
        strikes = record.get("strikes", 0)
        if hosted or strikes:
            host_lines.append(f"{name}: {hosted}")
            strike_lines.append(f"{name}: {strikes}")

    try:
        month_display = datetime.strptime(month_key, "%Y-%m").strftime("%B %Y")
    except ValueError:
        month_display = month_key

    embed = discord.Embed(
        title=f"{title_prefix} {month_display} Report",
        color=discord.Color.blurple()
    )
    embed.add_field(name="Hosting", value="\n".join(host_lines) or "No hosting logged.", inline=True)
    embed.add_field(name="Strikes (current totals)", value="\n".join(strike_lines) or "No strikes.", inline=True)
    return embed

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
    # Right now this holds the command-log channel, report channel, and the
    # AFK role — built to easily hold more server-wide settings later if needed.
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM bot_settings WHERE id = 1")
        row = cur.fetchone()
        cur.close()
        conn.close()
        return {
            "log_channel_id": row["log_channel_id"] if row else None,
            "report_channel_id": row["report_channel_id"] if row else None,
            "last_report_month": row["last_report_month"] if row else None,
            "afk_role_id": row["afk_role_id"] if row else None,
        }
    except Exception as e:
        print(f"⚠️ Failed to load bot settings: {e}")
        traceback.print_exc()
        return {"log_channel_id": None, "report_channel_id": None, "last_report_month": None, "afk_role_id": None}

def save_bot_settings(settings):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE bot_settings SET log_channel_id = %s, report_channel_id = %s, last_report_month = %s, afk_role_id = %s WHERE id = 1",
            (settings.get("log_channel_id"), settings.get("report_channel_id"), settings.get("last_report_month"), settings.get("afk_role_id"))
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

# === Events ===
# on_ready can fire more than once per process (Discord re-fires it on every
# reconnect, not just the first connect). This flag makes sure the slash
# command sync below only ever runs ONCE per process — repeating the full
# per-guild + global sync on every reconnect is what previously hammered
# Discord's API and got the bot rate-limited (Cloudflare error 1015 / HTTP 429).
_slash_synced = False

@bot.event
async def on_ready():
    global _slash_synced

    # Fires once the bot has fully connected to Discord. This is also where
    # we register all the slash ("/") commands so they show up in Discord's UI.
    print(f"Bot online as {bot.user}")

    # Render sets RENDER_EXTERNAL_URL automatically for every deployed service —
    # printing it here makes Render's log viewer turn it into a clickable link,
    # same as it does for its own "Available at your primary URL" line.
    site_url = os.getenv("RENDER_EXTERNAL_URL", "https://e3n.onrender.com")
    print(f"📊 Dashboard: {site_url}/dashboard")

    if not _slash_synced:
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
            _slash_synced = True
        except Exception as e:
            print(f"Slash command sync failed: {e}")
    else:
        print("Slash commands already synced this session — skipping re-sync on reconnect.")

    # Only start the daily check once — on_ready can fire again on reconnect
    if not check_monthly_report.is_running():
        check_monthly_report.start()

@tasks.loop(hours=24)
async def check_monthly_report():
    # Runs once a day. If today is the 1st of the month (and we haven't
    # already reported this rollover), post last month's hosting/strikes
    # report to the configured channel, then clear that month's hosting numbers.
    today = datetime.utcnow()
    if today.day != 1:
        return

    settings = load_bot_settings()
    prev_month = get_previous_month_key()

    if settings.get("last_report_month") == prev_month:
        return  # Already handled this month's rollover

    channel_id = settings.get("report_channel_id")
    if not channel_id:
        return  # No report channel configured — skip silently

    channel = bot.get_channel(channel_id)
    if not channel:
        return

    data = load_data()
    embed = build_month_report_embed(data, prev_month, title_prefix="📅")
    embed.set_footer(text="This month's hosting numbers have been cleared. Strikes are unaffected.")

    try:
        await channel.send(embed=embed)
    except discord.HTTPException as e:
        print(f"⚠️ Failed to send monthly report: {e}")
        return

    # Clear only the completed month's hosting numbers — strikes and other
    # months are left untouched
    for rec in data.values():
        rec.get("monthly", {}).pop(prev_month, None)
    save_data(data)

    settings["last_report_month"] = prev_month
    save_bot_settings(settings)

@check_monthly_report.before_loop
async def before_monthly_report():
    await bot.wait_until_ready()

@bot.after_invoke
async def log_command_usage(ctx):
    # Runs automatically after EVERY command finishes (any command, from
    # anyone) — posts a short summary to the log channel set via !settings.
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

@bot.hybrid_command(description="Export a specific month's hosting + strike report (defaults to current month)")
@discord.app_commands.describe(month="Month in YYYY-MM format, e.g. 2026-07 (defaults to the current month)")
@commands.has_permissions(manage_messages=True)
async def exportmonth(ctx, month: str = None):
    month_key = month or get_current_month_key()
    try:
        datetime.strptime(month_key, "%Y-%m")
    except ValueError:
        await ctx.send("❌ Use the format `YYYY-MM`, e.g. `2026-07`.")
        return

    data = load_data()
    embed = build_month_report_embed(data, month_key)
    await ctx.send(embed=embed)

# --- Info-lookup commands (open to everyone) ---
@bot.hybrid_command(description="Show info about a server member")
@discord.app_commands.describe(member="The member to look up (defaults to you)")
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author

    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    roles.reverse()
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

# --- AFK toggle (open to everyone, role configured via !settings) ---
@bot.hybrid_command(description="Toggle the AFK role on/off for yourself")
async def afk(ctx):
    settings = load_bot_settings()
    role_id = settings.get("afk_role_id")
    if not role_id:
        await ctx.send("❌ No AFK role has been configured yet. Ask an admin to set one via `!settings`.")
        return

    role = ctx.guild.get_role(role_id) if ctx.guild else None
    if not role:
        await ctx.send("❌ The configured AFK role no longer exists. Ask an admin to set a new one via `!settings`.")
        return

    try:
        if role in ctx.author.roles:
            await ctx.author.remove_roles(role, reason="AFK toggle")
            await ctx.send(f"👋 Welcome back, {ctx.author.mention}! AFK role removed.")
        else:
            await ctx.author.add_roles(role, reason="AFK toggle")
            await ctx.send(f"💤 {ctx.author.mention} is now AFK.")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to manage that role — check that my top role is above it.")

# --- Admin/owner settings (all combined into one command with buttons) ---
# A ChannelSelect is Discord's native channel-picker dropdown — the person
# clicks a channel from a list instead of typing "#channel-name" by hand.
class ChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, setting_key):
        # `setting_key` tells the callback below which setting to save —
        # "counting", "log", or "report" — so one class can handle all three.
        super().__init__(placeholder="Choose a channel...", channel_types=[discord.ChannelType.text])
        self.setting_key = setting_key

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]

        if self.setting_key == "counting":
            count_data = load_count_data()
            count_data["channel_id"] = channel.id
            count_data["current_count"] = 0
            count_data["last_user_id"] = None
            saved = save_count_data(count_data)
            result_text = f"🔢 Counting channel set to {channel.mention}. Next number is **1**."
        elif self.setting_key == "log":
            settings = load_bot_settings()
            settings["log_channel_id"] = channel.id
            saved = save_bot_settings(settings)
            result_text = f"📝 Command usage will now be logged to {channel.mention}."
        else:  # "report"
            settings = load_bot_settings()
            settings["report_channel_id"] = channel.id
            saved = save_bot_settings(settings)
            result_text = f"📅 Monthly reports will now be posted to {channel.mention}."

        if not saved:
            await interaction.response.edit_message(content="❌ Database error — the setting wasn't saved.", view=None)
            return
        await interaction.response.edit_message(content=result_text, view=None)

class ChannelPickerView(discord.ui.View):
    def __init__(self, setting_key):
        super().__init__(timeout=60)
        self.add_item(ChannelPicker(setting_key))

# Same idea as ChannelPicker above, but Discord's native role-picker dropdown —
# only used for the AFK role right now, but built the same way in case more
# role-based settings get added later.
class RolePicker(discord.ui.RoleSelect):
    def __init__(self, setting_key):
        super().__init__(placeholder="Choose a role...")
        self.setting_key = setting_key

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]

        settings = load_bot_settings()
        settings["afk_role_id"] = role.id
        saved = save_bot_settings(settings)

        if not saved:
            await interaction.response.edit_message(content="❌ Database error — the setting wasn't saved.", view=None)
            return
        await interaction.response.edit_message(content=f"💤 AFK role set to {role.mention}. `!afk` will now toggle it.", view=None)

class RolePickerView(discord.ui.View):
    def __init__(self, setting_key):
        super().__init__(timeout=60)
        self.add_item(RolePicker(setting_key))

# The main settings menu — one button per configurable setting. Each button
# checks its own permission when clicked, since a View's buttons don't support
# the @commands.has_permissions decorator that regular commands use.
class SettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Counting Channel", style=discord.ButtonStyle.primary, emoji="🔢")
    async def counting_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("🚫 Requires Administrator.", ephemeral=True)
            return
        await interaction.response.send_message("Pick the counting channel:", view=ChannelPickerView("counting"), ephemeral=True)

    @discord.ui.button(label="Toggle Counting", style=discord.ButtonStyle.secondary, emoji="⚙️")
    async def toggle_counting(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("🚫 Requires Administrator.", ephemeral=True)
            return
        count_data = load_count_data()
        count_data["enabled"] = not count_data.get("enabled", True)
        save_count_data(count_data)
        state = "on" if count_data["enabled"] else "off"
        await interaction.response.send_message(f"✅ Counting game turned **{state}**.", ephemeral=True)

    @discord.ui.button(label="Command Log Channel", style=discord.ButtonStyle.primary, emoji="📝")
    async def log_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("🚫 Only the server owner can change this.", ephemeral=True)
            return
        await interaction.response.send_message("Pick the command log channel:", view=ChannelPickerView("log"), ephemeral=True)

    @discord.ui.button(label="Report Channel", style=discord.ButtonStyle.primary, emoji="📅")
    async def report_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("🚫 Only the server owner can change this.", ephemeral=True)
            return
        await interaction.response.send_message("Pick the monthly report channel:", view=ChannelPickerView("report"), ephemeral=True)

    @discord.ui.button(label="AFK Role", style=discord.ButtonStyle.secondary, emoji="💤")
    async def afk_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("🚫 Requires Administrator.", ephemeral=True)
            return
        await interaction.response.send_message("Pick the role `!afk` should toggle:", view=RolePickerView("afk"), ephemeral=True)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

@bot.hybrid_command(description="Configure E3N's settings (counting channel, log channel, report channel, AFK role)")
async def settings(ctx):
    embed = discord.Embed(
        title="⚙️ E3N Settings",
        description="Pick what you'd like to configure below. Each button checks your permission when clicked.",
        color=discord.Color.blurple()
    )
    embed.add_field(name="🔢 Counting Channel / ⚙️ Toggle Counting / 💤 AFK Role", value="Requires Administrator", inline=False)
    embed.add_field(name="📝 Command Log / 📅 Report Channel", value="Requires Server Owner", inline=False)
    await ctx.send(embed=embed, view=SettingsView())

# --- Leaderboard display + its toggle/reset buttons ---
def build_leaderboard_embed(count_data, mode="correct"):
    # Builds either the "correct counts" or "times ruined" leaderboard embed,
    # depending on `mode`. Used by !countboard and its buttons below.
    users = count_data.get("users", {})

    if mode == "ruined":
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
    else:
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
# This one lets people switch between the "Correct" and "Ruined" leaderboards,
# plus an admin-only "Reset" button — all on the same message.
class LeaderboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.mode = "correct"

    @discord.ui.button(label="Correct", style=discord.ButtonStyle.primary, emoji="🔢")
    async def show_correct(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "correct"
        count_data = load_count_data()
        await interaction.response.edit_message(embed=build_leaderboard_embed(count_data, "correct"), view=self)

    @discord.ui.button(label="Ruined", style=discord.ButtonStyle.secondary, emoji="💀")
    async def show_ruined(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.mode = "ruined"
        count_data = load_count_data()
        await interaction.response.edit_message(embed=build_leaderboard_embed(count_data, "ruined"), view=self)

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
        await interaction.response.edit_message(embed=build_leaderboard_embed(count_data, self.mode), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

@bot.hybrid_command(description="Show the counting game leaderboard (correct counts or ruined counts)")
async def countboard(ctx):
    count_data = load_count_data()
    await ctx.send(embed=build_leaderboard_embed(count_data, "correct"), view=LeaderboardView())

@bot.hybrid_command(description="Show who's broken the count the most")
async def ruinedboard(ctx):
    count_data = load_count_data()
    await ctx.send(embed=build_leaderboard_embed(count_data, "ruined"), view=LeaderboardView())

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
            "`!countboard` — Show the counting leaderboard (toggle Correct/Ruined)\n"
            "`!ruinedboard` — Show who's broken the count the most\n"
            "`!userinfo [@member]` — Show info about a member (defaults to you)\n"
            "`!roleinfo @role` — Show info about a role\n"
            "`!afk` — Toggle the AFK role on/off for yourself\n"
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
            "`!resetstrikes @member` — Reset a member's strikes to 0\n"
            "`!exportmonth [YYYY-MM]` — Export a month's hosting + strike report (defaults to current month)"
        ),
        inline=False
    )
    embed.add_field(
        name="🛡️ Admin / Owner Settings",
        value="`!settings` — Configure counting channel, counting on/off, log channel, report channel, and AFK role (buttons + channel/role picker, permission-checked per option)",
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