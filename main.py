
from flask import Flask
from threading import Thread
import discord
from discord.ext import commands
import os
import json
import sys
import traceback
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from datetime import datetime
from dotenv import load_dotenv
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