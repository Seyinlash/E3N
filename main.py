from flask import Flask
from threading import Thread
import discord
from discord.ext import commands
import os
import json
from datetime import datetime
from dotenv import load_dotenv
import random

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

# === Load Token ===
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# === Bot Setup ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

DATA_FILE = "log_data.json"

def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

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

# === Events ===
@bot.event
async def on_ready():
    print(f"Bot online as {bot.user}")

# === Commands ===

@bot.command()
@commands.has_permissions(manage_messages=True)
async def loghost(ctx, member: discord.Member, count: int = 1):
    data = load_data()
    uid, month = ensure_member(data, member)
    data[uid]["monthly"][month] += count
    save_data(data)
    await ctx.send(f"📌 Logged {count} hosted event(s) for {data[uid]['display_name']}. This month: {data[uid]['monthly'][month]}")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def deletehost(ctx, member: discord.Member, count: int = 1):
    data = load_data()
    uid, month = ensure_member(data, member)
    current_count = data[uid]["monthly"].get(month, 0)
    if current_count > 0:
        removed = min(count, current_count)
        data[uid]["monthly"][month] -= removed
        save_data(data)
        await ctx.send(f"🗑️ Removed {removed} hosting log(s) for {data[uid]['display_name']}. Now: {data[uid]['monthly'][month]}")
    else:
        await ctx.send(f"❌ No hosting logs to delete for {data[uid]['display_name']} this month.")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def strike(ctx, member: discord.Member, count: int = 1):
    data = load_data()
    uid, _ = ensure_member(data, member)
    data[uid]["strikes"] += count
    save_data(data)
    await ctx.send(f"⚠️ Added {count} strike(s) to {data[uid]['display_name']}. Total: {data[uid]['strikes']}")

@bot.command()
async def strikes(ctx):
    data = load_data()
    if not data:
        await ctx.send("📭 No strike data recorded.")
        return

    out = "\n".join(f"{d['display_name']}: {d['strikes']}" for d in data.values())
    await ctx.send("**Strikes:**\n" + out)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def resetstrikes(ctx, member: discord.Member):
    data = load_data()
    uid, _ = ensure_member(data, member)
    data[uid]["strikes"] = 0
    save_data(data)
    await ctx.send(f"✅ Strikes reset for {data[uid]['display_name']}.")

@bot.command()
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

@bot.command(name="commands")
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
    embed.set_footer(text="Prefix: !")
    await ctx.send(embed=embed)

# === Run Bot ===
bot.run(TOKEN)