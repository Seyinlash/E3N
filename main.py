from flask import Flask
from threading import Thread
import discord
from discord.ext import commands, tasks
import os
import random
import json
import logging
from datetime import datetime
from dotenv import load_dotenv

# --- Flask Uptime Ping Server ---
app = Flask('')

@app.route('/')
def home():
    return "Ethan active."

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()

# --- Load Bot Token ---
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# --- Discord Setup ---
logging.basicConfig(level=logging.INFO)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="Ethan ", intents=intents, help_command=None)

DATA_FILE = "log_data.json"
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "log_data.json")
# --- Ensure Data File Exists ---

# --- Sassy Response Lines ---
strike_lines = [
    "⚠️ Strike recorded for **{name}**. That’s **{count}** now. We’re entering disappointment territory.",
    "📉 Another strike for **{name}**. Confidence level: decreasing.",
    "💥 Boom. **{name}** just got a strike. Total: **{count}**. Even AI can be disappointed."
]

loghost_lines = [
    "📌 Hosting logged for **{name}**. They're now at **{count}** for this month. Impressive... or expected.",
    "✅ Logged. **{name}** showed up. That's new.",
    "🔍 Activity confirmed for **{name}**. Tally updated: **{count}** times this month."
]

loa_on_lines = [
    "📌 **{name}** marked as LoA. We’ll try to survive without them. Again.",
    "📭 **{name}** is now LoA. Let’s hope it’s not permanent.",
    "💤 LoA applied to **{name}**. I’ll keep their chair warm. Not really."
]

loa_off_lines = [
    "☑️ **{name}** is back. Let’s see if they actually do anything.",
    "📣 **{name}** returned from LoA. Welcome back... I guess.",
    "🪖 LoA removed from **{name}**. Back to duty, soldier."
]

reset_strike_lines = [
    "✅ Strikes reset for **{name}**. Let’s pretend the past didn’t happen.",
    "🧽 Clean slate for **{name}**. Don’t mess it up again.",
    "📂 File wiped. **{name}** has 0 strikes... for now."
]

logs_sent_lines = [
    "🧾 Tactical report uploaded.",
    "📊 Here’s the situation, Captain.",
    "🔎 Logs compiled. Review at will."
]

# --- Data Functions ---
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

def ensure_member_record(data, member: discord.Member):
    uid = str(member.id)
    if uid not in data:
        data[uid] = {
            "display_name": member.display_name,
            "strikes": 0,
            "monthly": {},
            "loa": False
        }
    else:
        # Update display name to stay current, but keep loa and others intact
        data[uid]["display_name"] = member.display_name

    current_month = get_current_month_key()
    if "monthly" not in data[uid]:
        data[uid]["monthly"] = {}
    if current_month not in data[uid]["monthly"]:
        data[uid]["monthly"][current_month] = 0

    return uid, current_month

# --- Events ---
@bot.event
async def on_ready():
    print(f"E3N online. Logged in as {bot.user}")
    reset_monthly_hosting.start()

@tasks.loop(minutes=60)
async def reset_monthly_hosting():
    now = datetime.utcnow()
    if now.day == 1 and now.hour == 0:
        data = load_data()
        current_month = get_current_month_key()
        for uid in data:
            if "monthly" not in data[uid]:
                data[uid]["monthly"] = {}
            data[uid]["monthly"][current_month] = 0
        save_data(data)
        print("📅 Monthly hosting logs reset.")

# --- Commands ---

@bot.command()
async def logs(ctx):
    data = load_data()
    if not data:
        await ctx.send("📭 No personnel data exists yet.")
        return

    current_month = get_current_month_key()
    month_name = datetime.utcnow().strftime("%B")
    hosting_lines = []
    strike_lines = []

    sorted_data = sorted(data.values(), key=lambda x: x.get("display_name", ""))

    for record in sorted_data:
        # Show LoA visually by appending it to display_name here if flagged
        display_name = record.get("display_name", "Unknown")
        if record.get("loa", False) and "(LoA)" not in display_name:
            display_name += " (LoA)"

        hosted = record.get("monthly", {}).get(current_month, 0)
        strikes = record.get("strikes", 0)
        hosting_lines.append(f"{display_name}: {hosted}")
        strike_lines.append(f"{display_name}: {strikes}")

    if all(line.endswith(": 0") for line in hosting_lines) and all(line.endswith(": 0") for line in strike_lines):
        await ctx.send("🫥 No hosting or strike logs recorded this month, Captain — not even a blip.")
        return

    hosting_text = f"**{month_name} Hosting:**\n" + "\n".join(hosting_lines)
    strike_text = "**Strikes:**\n" + "\n".join(strike_lines)
    intro = random.choice(logs_sent_lines)

    await ctx.send(f"{intro}\n\n{hosting_text}\n\n{strike_text}")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def loghost(ctx, member: discord.Member, *, note: str = ""):
    data = load_data()
    uid, current_month = ensure_member_record(data, member)

    # Increment hosting count
    data[uid]["monthly"][current_month] += 1

    # LoA toggle check
    if note and "loa" in note.lower():
        if "(LoA)" not in data[uid]["display_name"]:
            data[uid]["display_name"] += " (LoA)"

    save_data(data)
    await ctx.send(
        f"📌 Logged hosted event for {data[uid]['display_name']}. This month: {data[uid]['monthly'][current_month]}"
    )

@bot.command()
@commands.has_permissions(manage_messages=True)
async def loa(ctx, member: discord.Member):
    data = load_data()
    uid, _ = ensure_member_record(data, member)
    if data[uid].get("loa", False):
        await ctx.send(f"❗ {member.display_name} is already marked as LoA, Captain.")
        return
    data[uid]["loa"] = True
    save_data(data)
    display_name = data[uid]["display_name"]
    if "(LoA)" not in display_name:
        display_name += " (LoA)"
    response = random.choice(loa_on_lines).format(name=display_name)
    await ctx.send(response)

@bot.command(name="unloa")
@commands.has_permissions(manage_messages=True)
async def unloa(ctx, member: discord.Member):
    data = load_data()
    uid, _ = ensure_member_record(data, member)
    if not data[uid].get("loa", False):
        await ctx.send(f"❗ {member.display_name} is not marked as LoA, Captain.")
        return
    data[uid]["loa"] = False
    # Remove (LoA) from display_name if present
    data[uid]["display_name"] = data[uid]["display_name"].replace(" (LoA)", "")
    save_data(data)
    response = random.choice(loa_off_lines).format(name=data[uid]["display_name"])
    await ctx.send(response)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def strike(ctx, member: discord.Member):
    data = load_data()
    uid, _ = ensure_member_record(data, member)
    data[uid]["strikes"] += 1
    save_data(data)
    response = random.choice(strike_lines).format(name=data[uid]["display_name"], count=data[uid]["strikes"])
    await ctx.send(response)

@bot.command()
async def strikes(ctx):
    data = load_data()
    if not data:
        await ctx.send("📭 No strike data recorded yet.")
        return

    strike_lines_list = []
    for record in data.values():
        display_name = record.get("display_name", "Unknown")
        if record.get("loa", False) and "(LoA)" not in display_name:
            display_name += " (LoA)"
        strikes = record.get("strikes", 0)
        strike_lines_list.append(f"{display_name}: {strikes}")

    await ctx.send("**Strikes:**\n" + "\n".join(strike_lines_list))

@bot.command()
@commands.has_permissions(manage_messages=True)
async def resetstrikes(ctx, member: discord.Member):
    data = load_data()
    uid, _ = ensure_member_record(data, member)
    data[uid]["strikes"] = 0
    save_data(data)
    response = random.choice(reset_strike_lines).format(name=data[uid]["display_name"])
    await ctx.send(response)

# --- E3N Personality & Fun Commands ---

e3n_quotes = [
    "Captain Reyes, you can do this.",
    "I believe in you, sir. This is what we're trained for.",
    "The mission comes first.",
    "Sir, I will accompany you to the end.",
    "That's one less bad guy!",
    "E3N systems green. Ready to execute."
]

e3n_personality = [
    "Tactical evaluation complete. You’re making sound decisions, Captain.",
    "The probability of success has increased by 12%. Encouraging.",
    "Emotionally, I am quite stable. Humor modules standing by.",
    "If I had a heart, I’d say this team makes me proud.",
    "You remind me of Captain Reyes. Efficient. Focused."
]

@bot.command()
async def hello(ctx):
    await ctx.send("Greetings, Captain. E3N, reporting for duty.")

@bot.command()
async def mission(ctx):
    await ctx.send("Mission parameters confirmed. Awaiting deployment orders, Captain.")

@bot.command()
async def joke(ctx):
    await ctx.send("Why did the drone cross the battlefield? To interface with the other side. Ha ha, humor protocols initiated.")

@bot.command()
async def status(ctx):
    await ctx.send("All systems functional. Combat readiness: 100%.")

@bot.command()
async def order66(ctx):
    await ctx.send("Killing all worms in the galaxy startiing with moffers.")

@bot.command()
async def quote(ctx):
    await ctx.send(random.choice(e3n_quotes))

@bot.command()
async def e3n(ctx):
    await ctx.send(random.choice(e3n_personality))

# --- Custom Help Command ---
@bot.command(name="help")
async def help_command(ctx):
    help_text = (
        "**E3N Command List:**\n"
        "`!hello` - E3N greets you (duh).\n"
        "`!mission` - Confirm mission parameters.\n"
        "`!joke` - E3N tries to be funny.\n"
        "`!status` - Combat readiness report.\n"
        "`!tts <message>` - Text to speech. Let E3N speak.\n"
        "`!quote` - Inspirational E3N quotes.\n"
        "`!e3n` - Get a random E3N personality line.\n"
        "\n"
        "**Hosting & Strike Commands (Staff only):**\n"
        "`!loghost <@member> [loa]` - Log hosting event. Add 'loa' to mark LoA.\n"
        "`!loa <@member>` - Mark a member as LoA.\n"
        "`!unloa <@member>` - Remove LoA mark.\n"
        "`!strike <@member>` - Give a strike.\n"
        "`!strikes` - Show all strikes.\n"
        "`!resetstrikes <@member>` - Reset strikes to zero.\n"
        "`!logs` - Show hosting and strikes logs.\n"
    )
    await ctx.send(help_text)

# --- Error Handling ---
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don’t have permission to use this command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❗ Missing required argument.")
    else:
        await ctx.send(f"⚠️ Error: {str(error)}")

# --- Launch the Bot ---
bot.run(TOKEN)
