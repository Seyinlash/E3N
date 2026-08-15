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

# === Counting Game Storage ===
COUNT_FILE = "counting_data.json"

def load_count_data():
    try:
        with open(COUNT_FILE, "r") as f:
            return json.load(f)
    except:
        return {
            "channel_id": None,
            "current_count": 0,
            "last_user_id": None,
            "best_streak": 0,
            "best_streak_holder": None,
            "users": {}
        }

def save_count_data(data):
    with open(COUNT_FILE, "w") as f:
        json.dump(data, f, indent=4)

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
        # Global sync (can take up to an hour to show up)
        await bot.tree.sync()

        # Guild sync (instant) — copies commands into every server the bot is in
        for guild in bot.guilds:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"Synced {len(synced)} slash command(s) to {guild.name}")
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

    # No counting channel set, or this message isn't in it
    if channel_id is None or message.channel.id != channel_id:
        return

    content = message.content.strip()

    # Only treat plain whole numbers as count attempts; anything else is left alone
    if not content.lstrip("-").isdigit():
        return

    number = int(content)
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
    save_data(data)
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
        save_data(data)
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
    save_data(data)
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
    save_data(data)
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
    save_count_data(count_data)
    await ctx.send(f"🔢 Counting channel set to {channel.mention}. Next number is **1**.")
 
@bot.hybrid_command(description="Show the counting game leaderboard")
async def countboard(ctx):
    count_data = load_count_data()
    users = count_data.get("users", {})
 
    if not users:
        await ctx.send("📭 No counting data yet.")
        return
 
    ranked = sorted(users.values(), key=lambda u: u["total_correct"], reverse=True)
    lines = [f"{i+1}. {u['display_name']} — {u['total_correct']} correct, {u['times_ruined']} ruined"
              for i, u in enumerate(ranked[:10])]
 
    embed = discord.Embed(
        title="🔢 Counting Leaderboard",
        description="\n".join(lines),
        color=discord.Color.gold()
    )
    if count_data.get("best_streak_holder"):
        embed.set_footer(text=f"All-time record: {count_data['best_streak']} (by {count_data['best_streak_holder']})")
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
        value="`!setcountchannel #channel` — Set the channel used for the counting game",
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
bot.run(TOKEN)
 