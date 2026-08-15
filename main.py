from flask import Flask
from threading import Thread
import discord
from discord.ext import commands
import os
import json
import sys
import re
import ast
import operator
import traceback
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from datetime import datetime
from dotenv import load_dotenv
from word2number import w2n
import random

# Force unbuffered stdout so Render logs show print() output immediately, in order
sys.stdout.reconfigure(line_buffering=True)

# === Keep-Alive Server ===
app = Flask('')

@app.route('/')
def home():
    return "Bot is running."

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

# === Database Setup ===
def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    masked = (DATABASE_URL[:40] + "...") if DATABASE_URL else "None"
    print(f"🔌 Connecting to database: {masked}")
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS members (
                user_id TEXT PRIMARY KEY,
                display_name TEXT,
                strikes INT DEFAULT 0,
                monthly JSONB DEFAULT '{}'::jsonb
            )
        """)
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS counting_users (
                user_id TEXT PRIMARY KEY,
                display_name TEXT,
                total_correct INT DEFAULT 0,
                times_ruined INT DEFAULT 0
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Database ready")
    except Exception as e:
        print(f"⚠️ Failed to initialize database: {e}")
        traceback.print_exc()

# === Strikes/Hosting Storage (members table) ===
def load_data():
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
    now = datetime.utcnow()
    return now.strftime("%Y-%m")

def ensure_member(data, member: discord.Member):
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

def ensure_count_user(data, member: discord.Member):
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
@bot.event
async def on_ready():
    print(f"Bot online as {bot.user}")
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

@bot.event
async def on_message(message: discord.Message):
    # Always let normal command processing happen (! and / prefix commands)
    await bot.process_commands(message)

    if message.author.bot:
        return

    count_data = load_count_data()
    channel_id = count_data.get("channel_id")

    # Counting turned off, no channel set, or this message isn't in it
    if not count_data.get("enabled", True) or channel_id is None or message.channel.id != channel_id:
        return

    content = message.content.strip()
    number = parse_count_attempt(content)

    # Not a recognized count attempt (number, math, or spelled-out word) — leave normal chat alone
    if number is None:
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

    # Correct count
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

# === Commands ===
# hybrid_command = works as BOTH "!command" and "/command" from one definition.
# discord.app_commands.describe() controls the text shown under each option in the slash UI.

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

@bot.hybrid_command(description="Set the channel used for the counting game")
@discord.app_commands.describe(channel="The channel to use for counting")
@commands.has_permissions(administrator=True)
async def setcountchannel(ctx, channel: discord.TextChannel):
    count_data = load_count_data()
    count_data["channel_id"] = channel.id
    count_data["current_count"] = 0
    count_data["last_user_id"] = None
    if not save_count_data(count_data):
        await ctx.send("❌ Database error — the channel wasn't saved. Check Render logs.")
        return
    await ctx.send(f"🔢 Counting channel set to {channel.mention}. Next number is **1**.")

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

def build_leaderboard_embed(count_data):
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
        value=(
            "`!setcountchannel #channel` — Set the channel used for the counting game\n"
            "`!counting on/off` — Turn the counting game on or off"
        ),
        inline=False
    )
    embed.set_footer(text="Works as ! commands or / slash commands")
    await ctx.send(embed=embed)

# === Error Handling ===
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
init_db()
bot.run(TOKEN)