import requests
import time
import json
import random
import sqlite3
import os
import re
import html
import threading
import firebase_admin
from firebase_admin import credentials, firestore
from http.server import HTTPServer, SimpleHTTPRequestHandler

# ==========================================
# Configuration
# ==========================================
BOT_TOKEN = "8874570334:AAFZskj1aaoklQwTSz-zo95OsusnaAseqIM"
ADMIN_ID = 8130737751
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"
BOT_USERNAME = "@Best99999_bot"

# 2oo9 API Configuration
API_2OO9_BASE = "https://api.2oo9.cloud/MXS47FLFX0U/tnevs/@public/api"
API_2OO9_KEY_DEFAULT = "MHF5UTYD3L7"

# Global states
current_db_mode = "sqlite"
db_firebase = None 
waiting_for_firebase = False
user_states = {}

# User & Cooldown States
user_cache = {} 
user_active_sessions = {} 
user_cooldowns = {} 

# Voltx Auto System States
voltx_auto_mode = True 
voltx_keys = [API_2OO9_KEY_DEFAULT]
force_join_status = False
force_join_channels = []

# OTP Forwarding States
otp_forward_groups = []
otp_button_link = "https://t.me/your_default_bot"
recent_success_otps = set()

voltx_dynamic_data = {} 
recent_traffic = []
daily_stats = {"date": "", "numbers": 0, "otps": 0}
daily_user_otps = {"date": "", "users": {}}

# Caching Variables
cached_services_kb = None
cached_countries_kb = {}
cached_leaderboard_text = ""

# ==========================================
# Dummy Web Server for Render Uptime
# ==========================================
class HealthCheckHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

def auto_cache_menu_thread():
    global cached_services_kb, cached_countries_kb, voltx_auto_mode, voltx_dynamic_data
    while True:
        try:
            if voltx_auto_mode and voltx_dynamic_data:
                service_hits = [(sid, s_data, sum(r["hits"] for r in s_data["ranges"].values())) for sid, s_data in voltx_dynamic_data.items()]
                top_services = sorted(service_hits, key=lambda x: x[2], reverse=True)[:15]
                
                new_srv_kb = {"inline_keyboard": []}
                row = []; styles = ["primary", "success", "danger"]; style_idx = 0
                for sid, data, hits in top_services:
                    safe_sid = html.escape(str(sid))
                    row.append({"text": safe_sid, "callback_data": f"srv_{safe_sid[:15]}", "style": styles[style_idx % 3], "icon_custom_emoji_id": data["emoji_id"]})
                    style_idx += 1
                    if len(row) == 2: new_srv_kb["inline_keyboard"].append(row); row = []
                if row: new_srv_kb["inline_keyboard"].append(row)
                new_srv_kb["inline_keyboard"].append([{"text": "✖ CLOSE PANEL", "callback_data": "close_panel", "icon_custom_emoji_id": "5438541186539232243", "style": "danger"}])
                
                cached_services_kb = new_srv_kb

                new_cnt_kb = {}
                for sid, data, hits in top_services:
                    safe_sid_short = html.escape(str(sid))[:15]
                    country_map = {}
                    for r, r_data in data["ranges"].items():
                        clean_r = str(r).replace("X", "")
                        if not re.match(r'^\d+$', clean_r): continue
                        c_code, c_name = get_country_info(clean_r)
                        if c_code not in country_map: country_map[c_code] = {"name": c_name, "hits": 0}
                        country_map[c_code]["hits"] += r_data["hits"]
                    
                    top_countries = sorted(country_map.items(), key=lambda x: x[1]["hits"], reverse=True)[:15]
                    
                    cnt_kb = {"inline_keyboard": []}
                    styles_c = ["primary", "success", "danger"]; style_idx_c = 0
                    std_service = detect_service("", sid)
                    rate = get_otp_reward(std_service)
                    
                    for c_code, c_data in top_countries:
                        c_name_full = c_data["name"]
                        parts = c_name_full.split(" ", 1)
                        emoji_char = parts[0]
                        clean_name = parts[1] if len(parts) > 1 else c_name_full
                        
                        btn_text = f"Other (+{c_code}) - {rate} TK" if "Other" in clean_name else f"{clean_name} (+{c_code}) - {rate} TK"
                        btn = {"text": btn_text, "callback_data": f"cc_{safe_sid_short}_{c_code}", "style": styles_c[style_idx_c % 3]}
                        if emoji_char in GLOBAL_BODY_EMOJIS: btn["icon_custom_emoji_id"] = GLOBAL_BODY_EMOJIS[emoji_char]
                            
                        cnt_kb["inline_keyboard"].append([btn])
                        style_idx_c += 1
                        
                    cnt_kb["inline_keyboard"].append([{"text": "🔙 BACK TO SERVICES", "callback_data": "back_to_services", "icon_custom_emoji_id": "5438541186539232243", "style": "danger"}])
                    new_cnt_kb[safe_sid_short] = cnt_kb
                    
                cached_countries_kb = new_cnt_kb
                
            global cached_leaderboard_text, daily_user_otps
            today = time.strftime("%Y-%m-%d")
            if daily_user_otps.get("date") != today:
                daily_user_otps["date"] = today
                daily_user_otps["users"] = {}
                
            top_users = sorted(daily_user_otps["users"].items(), key=lambda x: x[1], reverse=True)[:5]
            lb_msg = (
                "<b>╔═════════════════════════╗</b>\n"
                "<b>║  🏆 TODAY'S TOP 5 LEADERBOARD  ║</b>\n"
                "<b>╚═════════════════════════╝</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            )
            emoji_map = [("1️⃣", "5238176680098440792"), ("2️⃣", "5237806896299157399"), ("3️⃣", "5239965456667812809"), ("4️⃣", "5237911487342751418"), ("5️⃣", "5240278297790686165")]
            
            if not top_users: 
                lb_msg += "<i>No OTPs received today yet.</i>\n"
            else:
                for idx, (uid_str, otp_count) in enumerate(top_users):
                    u_data = get_user(int(uid_str))
                    fname = u_data["first_name"] if u_data else "User"
                    emoji_char, emoji_id = emoji_map[idx]
                    lb_msg += f"<blockquote><tg-emoji emoji-id=\"{emoji_id}\">{emoji_char}</tg-emoji> <b><a href='tg://user?id={uid_str}'>{html.escape(str(fname))}</a></b> ➜ <code>{otp_count} OTPs</code></blockquote>\n"
            lb_msg += "━━━━━━━━━━━━━━━━━━━━━━━━━"
            cached_leaderboard_text = lb_msg
            
        except Exception:
            pass
        time.sleep(5)

# Admin Settings
bot_settings = {
    "withdraw_on": True,
    "min_withdraw": 10.0,
    "support_link": "",
    "w_group": "",
    "auto_br_on": False,
    "auto_br_interval": 60,
    "cooldown": 5,
    "num_req": 1,
    "w_methods": ["bKash", "Nagad"],
    "otp_default_rate": 0.5,
    "otp_service_rates": {},
    "main_channel_link": ""
}

BOT_DATA_FILE = "bot_data.json"
USERS_LIST_FILE = "users_list.json"

def get_api_key():
    return random.choice(voltx_keys) if voltx_keys else API_2OO9_KEY_DEFAULT

def get_otp_reward(service_name):
    rates = bot_settings.get("otp_service_rates", {})
    val = rates.get(service_name, bot_settings.get("otp_default_rate", 0.5))
    return float(val)

def update_daily_stat(key, amount=1):
    global daily_stats
    today = time.strftime("%Y-%m-%d")
    if daily_stats.get("date") != today:
        daily_stats = {"date": today, "numbers": 0, "otps": 0}
    daily_stats[key] = daily_stats.get(key, 0) + amount

def load_local_data():
    global recent_traffic, voltx_dynamic_data, voltx_keys, force_join_status, force_join_channels, voltx_auto_mode, otp_forward_groups, otp_button_link, recent_success_otps, bot_settings, user_active_sessions, daily_stats, daily_user_otps
    if os.path.exists(BOT_DATA_FILE):
        try:
            with open(BOT_DATA_FILE, "r") as f:
                data = json.load(f)
                recent_traffic = data.get("recent_traffic", [])
                voltx_dynamic_data = data.get("voltx_dynamic_data", {})
                loaded_keys = data.get("voltx_keys", [])
                voltx_keys = loaded_keys if loaded_keys else [API_2OO9_KEY_DEFAULT]
                force_join_status = data.get("force_join_status", False)
                force_join_channels = data.get("force_join_channels", [])
                voltx_auto_mode = data.get("voltx_auto_mode", True)
                otp_forward_groups = data.get("otp_forward_groups", [])
                otp_button_link = data.get("otp_button_link", "https://t.me/your_default_bot")
                recent_success_otps = set(data.get("recent_success_otps", []))
                loaded_settings = data.get("bot_settings", {})
                for k, v in loaded_settings.items(): bot_settings[k] = v
                daily_stats = data.get("daily_stats", {"date": "", "numbers": 0, "otps": 0})
                daily_user_otps = data.get("daily_user_otps", {"date": "", "users": {}})
                user_active_sessions = data.get("user_active_sessions", {})
        except Exception as e:
            print(f"Error loading local data: {e}")

def save_local_data():
    global recent_traffic, voltx_dynamic_data, voltx_keys, force_join_status, force_join_channels, voltx_auto_mode, otp_forward_groups, otp_button_link, recent_success_otps, bot_settings, user_active_sessions, daily_stats
    try:
        with open(BOT_DATA_FILE, "w") as f:
            json.dump({
                "recent_traffic": recent_traffic, 
                "voltx_dynamic_data": voltx_dynamic_data,
                "voltx_keys": voltx_keys,
                "force_join_status": force_join_status,
                "force_join_channels": force_join_channels,
                "voltx_auto_mode": voltx_auto_mode,
                "otp_forward_groups": otp_forward_groups,
                "otp_button_link": otp_button_link,
                "recent_success_otps": list(recent_success_otps),
                "bot_settings": bot_settings,
                "user_active_sessions": user_active_sessions,
                "daily_stats": daily_stats,
                "daily_user_otps": daily_user_otps
            }, f)
    except Exception as e:
        print(f"Error saving local data: {e}")
        
    if current_db_mode == "firebase" and db_firebase:
        try:
            db_firebase.collection('settings').document('bot_config').set({
                "bot_settings": bot_settings,
                "force_join_status": force_join_status,
                "force_join_channels": force_join_channels,
                "otp_forward_groups": otp_forward_groups,
                "otp_button_link": otp_button_link,
                "voltx_keys": voltx_keys,
                "voltx_auto_mode": voltx_auto_mode
            }, merge=True)
        except: pass

cached_user_list = set()

def add_to_broadcast_list(user_id):
    global cached_user_list
    if not cached_user_list and os.path.exists(USERS_LIST_FILE):
        try:
            with open(USERS_LIST_FILE, "r") as f:
                cached_user_list = set(json.load(f))
        except: pass
        
    if user_id not in cached_user_list:
        cached_user_list.add(user_id)
        try:
            with open(USERS_LIST_FILE, "w") as f:
                json.dump(list(cached_user_list), f)
        except: pass

def get_all_user_ids():
    global user_cache
    users = set()
    for uid in user_cache.keys():
        users.add(int(uid))
    if os.path.exists(USERS_LIST_FILE):
        try:
            with open(USERS_LIST_FILE, "r") as f:
                for u in json.load(f): users.add(int(u))
        except: pass
    return list(users)

def get_bot_info():
    try:
        res = requests.get(BASE_URL + "getMe").json()
        if res.get("ok"): return res["result"]["username"]
    except Exception: pass
    return ""

def set_bot_commands():
    commands = [{"command": "start", "description": "✨ Open Main Menu"}]
    try: requests.post(BASE_URL + "setMyCommands", json={"commands": commands})
    except Exception: pass

def send_message(chat_id, text, reply_markup=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "text": apply_emojis(text), "parse_mode": parse_mode}
    if reply_markup: payload["reply_markup"] = reply_markup
    try: return requests.post(BASE_URL + "sendMessage", json=payload).json()
    except Exception: return None

def edit_message(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": apply_emojis(text), "parse_mode": parse_mode}
    if reply_markup: payload["reply_markup"] = reply_markup
    try: requests.post(BASE_URL + "editMessageText", json=payload)
    except Exception: pass

def answer_callback_query(callback_query_id, text="", show_alert=False):
    payload = {"callback_query_id": callback_query_id, "text": text, "show_alert": show_alert}
    requests.post(BASE_URL + "answerCallbackQuery", json=payload)

def delete_message(chat_id, message_id):
    payload = {"chat_id": chat_id, "message_id": message_id}
    requests.post(BASE_URL + "deleteMessage", json=payload)

def copy_message(chat_id, from_chat_id, message_id, reply_markup=None):
    payload = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
    if reply_markup: payload["reply_markup"] = reply_markup
    try: return requests.post(BASE_URL + "copyMessage", json=payload).json()
    except Exception: return None

def get_chat_details(chat_identifier):
    chat_identifier = str(chat_identifier).strip()
    if chat_identifier.startswith("https://t.me/"):
        chat_identifier = "@" + chat_identifier.split("/")[-1]
    elif not chat_identifier.startswith("@") and not chat_identifier.startswith("-100"):
        chat_identifier = "@" + chat_identifier
        
    url = BASE_URL + "getChat"
    res = requests.get(url, params={"chat_id": chat_identifier}).json()
    if res.get("ok"):
        chat = res["result"]
        chat_data = {
            "id": chat["id"],
            "username": "@" + chat["username"] if "username" in chat else "",
            "title": chat.get("title", "Private Channel"),
            "invite_link": chat.get("invite_link", "")
        }
        if not chat_data["invite_link"]:
            inv_res = requests.post(BASE_URL + "exportChatInviteLink", json={"chat_id": chat["id"]}).json()
            if inv_res.get("ok"):
                chat_data["invite_link"] = inv_res["result"]
        return chat_data
    return None

def is_user_joined(user_id):
    if not force_join_status or not force_join_channels: return True
    if user_id == ADMIN_ID: return True
    for ch in force_join_channels:
        try:
            res = requests.get(BASE_URL + "getChatMember", params={"chat_id": ch["id"], "user_id": user_id}).json()
            if res.get("ok"):
                status = res["result"]["status"]
                if status in ["left", "kicked"]: return False
            else: return False
        except: return False
    return True

GLOBAL_BODY_EMOJIS = {
    "➖": "5870818207383686839", "🚫": "5334807341109908955", "🖥": "5334880948259427772", 
    "🌐": "5334590977837403844", "🌟": "5337102391244263212", "⌛": "5337172996211648018", 
    "💬": "5337302974806922068", "🔐": "5337255927735163754", "⚠️": "5336944168944047463", 
    "🔥": "5337267511261960341", "💸": "5429612421977253466", "📊": "5353032893096567467", 
    "🔢": "5226929552319594190", "👤": "5352861489541714456", "🚀": "5352597830089347330", 
    "💎": "5352838545826420397", "✅": "5352694861990501856", "✨": "5352552689983067014", 
    "📱": "5337132498965010628", "🔗": "5420517437885943844", "❌": "5420130255174145507", 
    "⚙️": "5420155432272438703", "➕": "5420323438508155202", "🎁": "5420396762189831222", 
    "💳": "5190899075968441286", "🛡": "5190447043545438788", "💰": "5190576863226933563", 
    "🟢": "5192812028632274956", "🌍": "5780471598922337683", "📌": "5318986077455795572", 
    "🆔": "5226929552319594190", "📈": "5352877703043258544", "🏦": "5429612421977253466", 
    "🔍": "5463352748751753567", "🔑": "5197288647275071607", "🏆": "5240021484516185513", 
    "👥": "5420145051336485498", "💵": "5429612421977253466", "👑": "5352838545826420397",
    "🇺🇸": "5913463998522592692", "🇺🇦": "5911406692007941050", "🇵🇱": "5913550391789752571", 
    "🇰🇿": "5913724621433082323", "🇨🇳": "5913779335021466780", "🇧🇩": "5911365056594973179"
}

def apply_emojis(text):
    hidden = []
    def hide(match):
        hidden.append(match.group(0))
        return f"__TG_EMOJI_{len(hidden)-1}__"
    text = re.sub(r'<tg-emoji[^>]*>.*?</tg-emoji>', hide, text)
    for char, eid in GLOBAL_BODY_EMOJIS.items():
        text = text.replace(char, f'<tg-emoji emoji-id="{eid}">{char}</tg-emoji>')
    for i, h in enumerate(hidden):
        text = text.replace(f"__TG_EMOJI_{i}__", h)
    return text

PREMIUM_APPS = {
    "Facebook": {"emoji": "📘", "id": "5429172110520003976"},
    "WhatsApp": {"emoji": "💬", "id": "5429612632430654504"},
    "Telegram": {"emoji": "✈️", "id": "5429136513831057777"},
    "Instagram": {"emoji": "📸", "id": "5429478178479447442"},
    "Google": {"emoji": "🔍", "id": "5429558795015593080"},
    "Microsoft": {"emoji": "🪟", "id": "5979047775470358891"},
    "TikTok": {"emoji": "🎵", "id": "5429132656950419591"},
    "Bkash": {"emoji": "🏦", "id": "5431552076452766597"},
    "Binance": {"emoji": "💱", "id": "5429438106434575354"},
    "Snapchat": {"emoji": "👻", "id": "5429398137468919845"},
    "Uber": {"emoji": "🚗", "id": "5298715455316303708"},
    "Discord": {"emoji": "🎬", "id": "5429594374524676604"},
    "Amazon": {"emoji": "🌟", "id": "5431358656895568355"},
    "Viber": {"emoji": "💜", "id": "5429470576387335368"},
    "Twitter": {"emoji": "🐦", "id": "5431899135580087595"},
    "Netflix": {"emoji": "🎥", "id": "5431641055290235797"},
    "Spotify": {"emoji": "🎵", "id": "5429235839244739644"},
    "ChatGPT": {"emoji": "🤖", "id": "5429503209548847635"},
    "Imo": {"emoji": "💭", "id": "5431378937731129128"},
    "Other": {"emoji": "📶", "id": "5429353834881261942"}
}

SERVICE_SMS_KEYWORDS = {
    "Facebook": ["facebook", "fb code", "fb", "meta"],
    "WhatsApp": ["whats", "whatsapp", "whatsapp code"],
    "Telegram": ["telegram", "tg code"],
    "Instagram": ["instagram", "ig code"],
    "Google": ["google", "Googl"],
    "Microsoft": ["microsoft", "micro", "Microsof", "xbox"],
    "TikTok": ["tiktok", "tik tok"],
    "Bkash": ["bkash"],
    "Binance": ["binance", "bnb"],
    "Snapchat": ["snapchat", "snap"],
    "Uber": ["uber"],
    "Discord": ["discord"],
    "Amazon": ["amazon", "aws"],
    "Viber": ["viber"],
    "Twitter": ["twitter", "x.com"],
    "Netflix": ["netflix"],
    "Spotify": ["spotify"],
    "ChatGPT": ["openai", "chatgpt"],
    "Imo": ["imo code", "imo"]
}

COUNTRY_CODES = {
    "1": "🇺🇸 USA/Canada", "380": "🇺🇦 Ukraine", "48": "🇵🇱 Poland", "7": "🇰🇿 Kazakhstan",
    "86": "🇨🇳 China", "880": "🇧🇩 Bangladesh"
}

def get_country_info(range_str):
    clean_range = str(range_str or "").replace("X", "")
    for code, name in sorted(COUNTRY_CODES.items(), key=lambda x: len(x[0]), reverse=True):
        if clean_range.startswith(code): return code, name
    return clean_range[:3], f"🏳️ Other (+{clean_range[:3]})"

def detect_service(message_text, raw_sid=""):
    msg_lower = str(message_text).lower()
    sid_lower = str(raw_sid).lower()
    for service, keywords in SERVICE_SMS_KEYWORDS.items():
        for kw in keywords:
            if re.search(rf'\b{re.escape(kw)}\b', msg_lower) or kw in msg_lower: return service
    for service in PREMIUM_APPS.keys():
        if service.lower() in sid_lower: return service
    return "Other"

def get_service_info_html(service_name):
    app_info = PREMIUM_APPS.get(service_name, PREMIUM_APPS["Other"])
    emoji_id = app_info["id"]
    normal_emoji = app_info["emoji"]
    return f'<tg-emoji emoji-id="{emoji_id}">{normal_emoji}</tg-emoji> <b>{html.escape(service_name.upper())}</b>', emoji_id

def extract_otp_code(message_text):
    match = re.search(r'\b(\d{3}[\s-]?\d{3,4}|\d{4,8})\b', str(message_text))
    if match: return match.group(1)
    return "COPY OTP"

def deliver_to_inbox(user_id, service_name, raw_number, msg_text, current_balance, reward):
    service_html, srv_eid = get_service_info_html(service_name)
    clean_raw_number = str(raw_number).lstrip('+') 
    text = (
        "<b>╔═════════════════════════╗</b>\n"
        "<b>║  🎉 OTP RECEIVED INBOX!  ║</b>\n"
        "<b>╚═════════════════════════╝</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>{service_html} ➜ <code>+{clean_raw_number}</code></blockquote>\n"
        f"<blockquote>➕ <b>ADDED REWARD</b>  ➜ <code>+{reward:.2f} TK</code></blockquote>\n"
        f"<blockquote>💳 <b>TOTAL BALANCE</b> ➜ <code>{current_balance:.2f} TK</code></blockquote>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    otp = extract_otp_code(msg_text)
    markup = {"inline_keyboard": [[{"text": f"🔑 OTP CODE: {otp}", "icon_custom_emoji_id": srv_eid, "copy_text": {"text": otp}, "style": "success"}]]}
    send_message(user_id, text, reply_markup=markup)

def generate_otp_display(service_name, raw_number, message_text):
    c_code, c_name = get_country_info(raw_number)
    parts = c_name.split(" ", 1)
    country_emoji = parts[0]
    masked_number = f"{raw_number[:3]}DXA{raw_number[-3:]}" if len(raw_number) > 6 else raw_number
    service_html, srv_eid = get_service_info_html(service_name)
    
    text = (
        "<b>╔═════════════════════════╗</b>\n"
        "<b>║   ⚡ LIVE OTP FORWARDED   ║</b>\n"
        "<b>╚═════════════════════════╝</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>{service_html} ➜ {country_emoji} <code>{html.escape(masked_number)}</code></blockquote>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    otp = extract_otp_code(message_text)
    clean_range = str(raw_number)[:5] if len(str(raw_number)) >= 5 else str(raw_number)
    deep_link = f"https://t.me/{BOT_USERNAME}?start=alloc_{clean_range}_{service_name.lower()}"
    
    markup = {"inline_keyboard": []}
    row1 = []
    main_channel_link = bot_settings.get("main_channel_link", "")
    if main_channel_link:
        row1.append({"text": "📢 CHANNEL", "url": main_channel_link, "icon_custom_emoji_id": "5429353834881261942", "style": "primary"})
    row1.append({"text": f"🔑 {otp}", "icon_custom_emoji_id": srv_eid, "copy_text": {"text": otp}, "style": "success"})
    markup["inline_keyboard"].append(row1)
    markup["inline_keyboard"].append([{"text": "⚡ GET INSTANT NUMBER", "url": deep_link, "icon_custom_emoji_id": "5429167978761461870", "style": "danger"}])
    return text, markup

def send_otp_to_groups(formatted_text, markup):
    global otp_forward_groups
    if not otp_forward_groups: return False
    sent_any = False
    for group_id in otp_forward_groups:
        resp = send_message(group_id, formatted_text, reply_markup=markup)
        if resp and resp.get("ok"): sent_any = True
        time.sleep(1) 
    return sent_any

def fetch_live_access():
    headers = {"mauthapi": get_api_key()}
    try:
        res = requests.get(f"{API_2OO9_BASE}/liveaccess", headers=headers, timeout=10)
        data = res.json()
        if data.get("meta", {}).get("code") == 200: return data.get("data", {}).get("services", [])
    except: pass
    return []

def fetch_live_number(rid):
    headers = {"mauthapi": get_api_key(), "Content-Type": "application/json"}
    payload = {"rid": str(rid)}
    try:
        res = requests.post(f"{API_2OO9_BASE}/getnum", headers=headers, json=payload, timeout=10)
        data = res.json()
        if data.get("meta", {}).get("code") == 200: return data.get("data", {})
    except: pass
    return None

def voltx_console_listener():
    global recent_traffic, voltx_dynamic_data
    cycle_count = 0
    while True:
        try:
            headers = {"mauthapi": get_api_key()}
            res = requests.get(f"{API_2OO9_BASE}/console", headers=headers, timeout=10)
            data = res.json()
            if data.get("meta", {}).get("code") == 200:
                hits = data.get("data", {}).get("hits", [])
                new_traffic, seen_signatures = [], set()
                current_time = int(time.time())
                
                for h in hits:
                    sig = f"{h.get('time', 0)}_{h.get('range', '')}"
                    if sig not in seen_signatures:
                        h['local_receive_time'] = current_time 
                        new_traffic.append(h)
                        seen_signatures.add(sig)
                        
                        raw_sid = h.get("sid") or "Unknown"
                        raw_msg = h.get("message") or ""
                        raw_range = str(h.get("range", "")).replace("X", "")
                        
                        if raw_range:
                            detected_sid = detect_service(raw_msg, raw_sid)
                            app_info = PREMIUM_APPS.get(detected_sid, PREMIUM_APPS["Other"])
                            emoji_id, normal_emoji = app_info["id"], app_info["emoji"]
                            
                            if detected_sid not in voltx_dynamic_data:
                                voltx_dynamic_data[detected_sid] = {"emoji_id": emoji_id, "normal_emoji": normal_emoji, "ranges": {}}
                            if raw_range not in voltx_dynamic_data[detected_sid]["ranges"]:
                                voltx_dynamic_data[detected_sid]["ranges"][raw_range] = {"last_seen": current_time, "hits": 0}
                            voltx_dynamic_data[detected_sid]["ranges"][raw_range]["last_seen"] = current_time
                            voltx_dynamic_data[detected_sid]["ranges"][raw_range]["hits"] += 1

                fifteen_mins_ago = current_time - 900
                for h in recent_traffic:
                    if h.get('local_receive_time', 0) >= fifteen_mins_ago:
                        sig = f"{h.get('time', 0)}_{h.get('range', '')}"
                        if sig not in seen_signatures:
                            new_traffic.append(h)
                            seen_signatures.add(sig)
                        
                new_traffic.sort(key=lambda x: x.get('local_receive_time', 0), reverse=True)
                recent_traffic = new_traffic

                services_to_delete = []
                for sid, s_data in voltx_dynamic_data.items():
                    ranges_to_delete = []
                    for r, r_data in s_data["ranges"].items():
                        if current_time - r_data["last_seen"] > 300: ranges_to_delete.append(r)
                    for r in ranges_to_delete: del s_data["ranges"][r]
                    if not s_data["ranges"]: services_to_delete.append(sid)
                for sid in services_to_delete: del voltx_dynamic_data[sid]

                cycle_count += 1
                if cycle_count % 3 == 0: save_local_data()
        except Exception: pass
        time.sleep(10)

def voltx_sms_listener():
    global recent_success_otps, otp_forward_groups, user_active_sessions
    group_sent_otps = set() 
    while True:
        try:
            headers = {"mauthapi": get_api_key(), "Content-Type": "application/json"}
            res = requests.get(f"{API_2OO9_BASE}/success-otp", headers=headers, timeout=15)
            
            if res.status_code == 200:
                data = res.json()
                otps = []
                if isinstance(data, dict):
                    if "data" in data and isinstance(data["data"], list): otps = data["data"]
                    elif "data" in data and isinstance(data["data"], dict):
                        if "otps" in data["data"]: otps = data["data"]["otps"]
                        elif "hits" in data["data"]: otps = data["data"]["hits"]
                    elif "otps" in data: otps = data["otps"]
                    elif "hits" in data: otps = data["hits"]
                elif isinstance(data, list): otps = data
                    
                for otp_data in reversed(otps):
                    msg_text = str(otp_data.get("message", otp_data.get("sms", otp_data.get("code", ""))))
                    raw_number = str(otp_data.get("number", otp_data.get("phone", "")))
                    raw_service = str(otp_data.get("sid", otp_data.get("service", "Unknown")))
                    
                    if not msg_text or not raw_number: continue
                    sig = f"{raw_number}_{msg_text}"
                    detected_service = detect_service(msg_text, raw_service)
                    
                    if sig not in group_sent_otps:
                        group_sent_otps.add(sig)
                        if otp_forward_groups:
                            formatted_message, markup = generate_otp_display(detected_service, raw_number, msg_text)
                            send_otp_to_groups(formatted_message, markup)
                    
                    if sig not in recent_success_otps:
                        recent_success_otps.add(sig)
                        owner_id = None
                        last_8_digits = raw_number[-8:] if len(raw_number) > 8 else raw_number
                        for active_num, uid in list(user_active_sessions.items()):
                            if active_num.endswith(last_8_digits):
                                owner_id = uid
                                del user_active_sessions[active_num]
                                break
                                
                        if owner_id:
                            reward = get_otp_reward(detected_service)
                            update_user_stats(owner_id, reward, 0)
                            user_balance = get_user(owner_id).get("balance", 0.0)
                            deliver_to_inbox(owner_id, detected_service, raw_number, msg_text, user_balance, reward)
                            
                            today_date = time.strftime("%Y-%m-%d")
                            if daily_user_otps.get("date") != today_date:
                                daily_user_otps["date"] = today_date
                                daily_user_otps["users"] = {}
                            uid_str = str(owner_id)
                            daily_user_otps["users"][uid_str] = daily_user_otps["users"].get(uid_str, 0) + 1
                        
                        update_daily_stat("otps", 1)
                        save_local_data()
                        time.sleep(1) 
        except Exception: pass
        time.sleep(10)

def init_sqlite():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, first_name TEXT DEFAULT 'User', balance REAL DEFAULT 0.0, total_invites INTEGER DEFAULT 0)")
    try: cursor.execute("ALTER TABLE users ADD COLUMN first_name TEXT DEFAULT 'User'")
    except sqlite3.OperationalError: pass
    try: cursor.execute("ALTER TABLE users ADD COLUMN total_otps INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    conn.commit()
    conn.close()

def init_firebase_from_file():
    global current_db_mode, db_firebase, bot_settings, force_join_status, force_join_channels, otp_forward_groups, otp_button_link, voltx_keys, voltx_auto_mode
    if os.path.exists("temp_firebase.json"):
        try:
            if not firebase_admin._apps: firebase_admin.initialize_app(credentials.Certificate("temp_firebase.json"))
            db_firebase = firestore.client()
            current_db_mode = "firebase"
            doc = db_firebase.collection('settings').document('bot_config').get()
            if doc.exists:
                data = doc.to_dict()
                if "bot_settings" in data: bot_settings.update(data["bot_settings"])
                if "force_join_status" in data: force_join_status = data["force_join_status"]
                if "force_join_channels" in data: force_join_channels = data["force_join_channels"]
                if "otp_forward_groups" in data: otp_forward_groups = data["otp_forward_groups"]
                if "otp_button_link" in data: otp_button_link = data["otp_button_link"]
                if "voltx_keys" in data: voltx_keys = data["voltx_keys"]
                if "voltx_auto_mode" in data: voltx_auto_mode = data["voltx_auto_mode"]
        except Exception as e: print(f"Firebase Connect Error: {e}")

def get_user(user_id):
    global current_db_mode, db_firebase, user_cache
    if user_id in user_cache: return user_cache[user_id]
    if current_db_mode == "firebase" and db_firebase:
        doc = db_firebase.collection('users').document(str(user_id)).get()
        if doc.exists:
            user_data = doc.to_dict()
            user_cache[user_id] = user_data 
            return user_data
        return None
    else: 
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT first_name, balance, total_invites FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        if row: 
            user_data = {"user_id": user_id, "first_name": row[0], "balance": row[1], "total_invites": row[2]}
            user_cache[user_id] = user_data 
            return user_data
        return None

def add_user(user_id, first_name="User"):
    global current_db_mode, db_firebase, user_cache
    add_to_broadcast_list(user_id) 
    if user_id in user_cache and user_cache[user_id]["first_name"] == first_name: return 
    if current_db_mode == "firebase" and db_firebase:
        doc_ref = db_firebase.collection('users').document(str(user_id))
        if not doc_ref.get().exists:
            new_data = {"user_id": user_id, "first_name": first_name, "balance": 0.0, "total_invites": 0}
            doc_ref.set(new_data)
            user_cache[user_id] = new_data
        else: 
            doc_ref.update({"first_name": first_name})
            if user_id in user_cache: user_cache[user_id]["first_name"] = first_name
    else: 
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id, first_name, balance, total_invites) VALUES (?, ?, 0.0, 0)", (user_id, first_name))
        cursor.execute("UPDATE users SET first_name = ? WHERE user_id = ?", (first_name, user_id))
        conn.commit()
        conn.close()
        if user_id not in user_cache: user_cache[user_id] = {"user_id": user_id, "first_name": first_name, "balance": 0.0, "total_invites": 0}
        else: user_cache[user_id]["first_name"] = first_name

def update_user_stats(user_id, balance_add, invite_add):
    global current_db_mode, db_firebase, user_cache
    bal_add = float(balance_add)
    inv_add = int(invite_add)
    if user_id not in user_cache: get_user(user_id)
    if user_id in user_cache:
        user_cache[user_id]["balance"] = round(user_cache[user_id]["balance"] + bal_add, 2)
        user_cache[user_id]["total_invites"] += inv_add
    if current_db_mode == "firebase" and db_firebase:
        db_firebase.collection('users').document(str(user_id)).update({"balance": firestore.Increment(bal_add), "total_invites": firestore.Increment(inv_add)})
    else: 
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance + ?, total_invites = total_invites + ? WHERE user_id = ?", (bal_add, inv_add, user_id))
        conn.commit()
        conn.close()

def get_total_users(): return len(get_all_user_ids()) 

# Keyboards
def get_main_keyboard(user_id):
    keyboard_layout = [
        [{"text": "⚡ GET NUMBER", "icon_custom_emoji_id": "5456259593082522998", "style": "danger"},
         {"text": "📈 LIVE TRAFFIC", "icon_custom_emoji_id": "5429571662737611814", "style": "primary"}],
        [{"text": "👥 INVITE FRIENDS", "icon_custom_emoji_id": "5384394344859974865", "style": "success"},
         {"text": "💳 WALLET & PAY", "icon_custom_emoji_id": "5429105001655999635", "style": "danger"}],
        [{"text": "🏆 LEADERBOARD", "icon_custom_emoji_id": "5240021484516185513", "style": "primary"}]
    ]
    if user_id == ADMIN_ID:
        keyboard_layout.append([{"text": "👑 OWNER PANEL", "icon_custom_emoji_id": "5429427051188756948", "style": "success"}])
    return {"keyboard": keyboard_layout, "resize_keyboard": True}

def get_admin_inline_keyboard():
    global current_db_mode
    db_status = "🟢 SQLITE ACTIVE" if current_db_mode == "sqlite" else "🔥 FIREBASE ACTIVE"
    return {
        "inline_keyboard": [
            [{"text": "🔑 VOLTX SETTINGS", "callback_data": "manage_voltx", "style": "danger"}],
            [{"text": "📣 BROADCAST", "callback_data": "broadcast_menu", "style": "primary"},
             {"text": "🔗 FORCE JOIN", "callback_data": "manage_fj", "style": "success"}],
            [{"text": "🛡 OTP GROUP", "callback_data": "manage_otp_group", "style": "danger"},
             {"text": "👤 USER CONTROL", "callback_data": "user_control", "style": "primary"}],
            [{"text": "⚙️ DXA SYSTEM CONTROL", "callback_data": "dxa_control", "style": "danger"}],
            [{"text": "🔥 UPLOAD FIREBASE JSON", "callback_data": "upload_firebase", "style": "primary"}],
            [{"text": db_status, "callback_data": "db_status", "style": "success"}],
            [{"text": "✖ CLOSE PANEL", "callback_data": "close_panel", "style": "danger"}]
        ]
    }

def get_force_join_alert_keyboard():
    kb = {"inline_keyboard": []}
    for ch in force_join_channels:
        name = ch.get("title", ch.get("username", "Our Official Channel"))
        url = ch.get("invite_link", "")
        if not url and ch.get("username"): url = f"https://t.me/{ch['username'].replace('@', '')}"
        kb["inline_keyboard"].append([{"text": f"📢 JOIN {name.upper()}", "url": url, "icon_custom_emoji_id": "5420517437885943844", "style": "danger"}])
    kb["inline_keyboard"].append([{"text": "✅ VERIFY JOINED", "callback_data": "check_fj_joined", "icon_custom_emoji_id": "5352694861990501856", "style": "success"}])
    return kb

def get_owner_panel_text():
    return (
        "<b>╔═════════════════════════╗</b>\n"
        "<b>║   👑 SYSTEM OWNER ZONE  ║</b>\n"
        "<b>╚═════════════════════════╝</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>📊 LIVE SYSTEM STATISTICS</b>\n"
        "— — — — — — — — — — — — —\n"
        f"<blockquote>👤 <b>TOTAL USERS</b>  ➜ <code>{get_total_users()} Users</code></blockquote>\n"
        f"<blockquote>📱 <b>TODAY NUMBERS</b> ➜ <code>{daily_stats['numbers']} Requested</code></blockquote>\n"
        f"<blockquote>💬 <b>TODAY OTPS</b>    ➜ <code>{daily_stats['otps']} Received</code></blockquote>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

def get_leaderboard_text():
    global cached_leaderboard_text
    if cached_leaderboard_text: return cached_leaderboard_text
    return "⏳ <b>Loading live leaderboard, please wait...</b>"

def get_live_traffic_content():
    global recent_traffic
    hits_to_show = recent_traffic
    markup = {"inline_keyboard": [[{"text": "🔄 REFRESH TRAFFIC", "callback_data": "refresh_traffic", "icon_custom_emoji_id": "5229111790842952353", "style": "primary"}]]}
    if not hits_to_show:
        return (
            "<b>╔═════════════════════════╗</b>\n"
            "<b>║  📈 15M LIVE TRAFFIC MONITOR ║</b>\n"
            "<b>╚═════════════════════════╝</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>No active traffic recorded in last 15 minutes.</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━"
        ), markup

    service_counts = {}
    for h in hits_to_show:
        raw_sid = h.get("sid") or "Unknown"
        raw_msg = h.get("message") or ""
        detected_sid = detect_service(raw_msg, raw_sid)
        app_info = PREMIUM_APPS.get(detected_sid, PREMIUM_APPS["Other"])
        if detected_sid not in service_counts: service_counts[detected_sid] = {"count": 0, "emoji_id": app_info["id"], "normal_emoji": app_info["emoji"]}
        service_counts[detected_sid]["count"] += 1

    sorted_services = sorted(service_counts.items(), key=lambda item: item[1]["count"], reverse=True)[:6]
    msg = (
        "<b>╔═════════════════════════╗</b>\n"
        "<b>║  📈 15M LIVE TRAFFIC MONITOR ║</b>\n"
        "<b>╚═════════════════════════╝</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    for i, (sid, data) in enumerate(sorted_services):
        msg += f"<blockquote><tg-emoji emoji-id=\"{data['emoji_id']}\">{data['normal_emoji']}</tg-emoji> <b>{html.escape(str(sid))}</b> ➜ 🔥 <code>{data['count']} OTPs</code></blockquote>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━"
    return msg, markup

def get_services_content():
    global cached_services_kb
    if cached_services_kb: return "<b>📱 Select Your Desired Service:</b>", cached_services_kb
    return "⏳ <b>Loading available services, please try again...</b>", None

def get_countries_content(sid_short):
    global cached_countries_kb
    if sid_short in cached_countries_kb: return "<b>🌍 Select Available Country:</b>", cached_countries_kb[sid_short], None
    return None, None, "❌ Out of stock for this service currently."

def get_number_allocation_content(sid_short, c_code, user_id=None):
    global voltx_auto_mode, voltx_dynamic_data, user_active_sessions, bot_settings, otp_button_link
    target_ranges = []
    full_sid = sid_short
    
    if voltx_auto_mode:
        for sid, data in voltx_dynamic_data.items():
            if sid.lower().startswith(sid_short.lower()):
                full_sid = sid
                for r, r_data in data["ranges"].items():
                    if c_code.startswith(r) or r.startswith(c_code): target_ranges.append((r, r_data["hits"]))
                break
        target_ranges.sort(key=lambda x: x[1], reverse=True)
        best_ranges = [x[0] for x in target_ranges[:3]]
    else:
        services_data = fetch_live_access()
        for s in services_data:
            sid_val = s.get('sid') or ""
            if sid_val.lower().startswith(sid_short.lower()):
                full_sid = sid_val
                for r in s.get('ranges', []):
                    clean_r = str(r).replace("X", "")
                    if c_code.startswith(clean_r) or clean_r.startswith(c_code):
                        if clean_r not in target_ranges: target_ranges.append(clean_r)
                break
        best_ranges = target_ranges[:3]
            
    if not best_ranges: best_ranges = [c_code]
    req_count = bot_settings.get("num_req", 1)
    fetched_numbers = []
    
    for _ in range(req_count):
        selected_rid = random.choice(best_ranges)
        num_data = fetch_live_number(selected_rid)
        if num_data:
            full_number = html.escape(str(num_data.get("full_number", "")))
            country = html.escape(str(num_data.get("country", "Unknown")))
            operator = html.escape(str(num_data.get("operator", "Unknown")))
            fetched_numbers.append((full_number, country, operator))
            if user_id and full_number: user_active_sessions[str(full_number)] = user_id
    
    if fetched_numbers:
        update_daily_stat("numbers", len(fetched_numbers))
        save_local_data()
        service_html, srv_eid = get_service_info_html(full_sid)
        _, country_with_flag = get_country_info(c_code)
        
        msg = (
            "<b>╔═════════════════════════╗</b>\n"
            "<b>║  ⚡ INSTANT NUMBER ALLOCATED ║</b>\n"
            "<b>╚═════════════════════════╝</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<blockquote>{service_html} ➜ {country_with_flag}</blockquote>\n"
            "<blockquote>⏳ <b>Validity:</b> <code>15 Minutes Active</code></blockquote>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        kb = {"inline_keyboard": []}
        for f_num, ctry, op in fetched_numbers:
            clean_f_num = str(f_num).lstrip('+') 
            kb["inline_keyboard"].append([{"text": f"📱 +{clean_f_num}", "icon_custom_emoji_id": "5226929552319594190", "copy_text": {"text": f"+{clean_f_num}"}, "style": "primary"}])
        kb["inline_keyboard"].append([
            {"text": "🔄 CHANGE NUMBER", "icon_custom_emoji_id": "5429386648431405093", "callback_data": f"cc_{sid_short}_{c_code}", "style": "danger"},
            {"text": "💬 LIVE OTP GROUP", "icon_custom_emoji_id": "5314366268898300483", "url": otp_button_link, "style": "success"}
        ])
        kb["inline_keyboard"].append([{"text": "🔙 BACK TO SERVICES", "icon_custom_emoji_id": "5438541186539232243", "callback_data": f"srv_{sid_short}", "style": "danger"}])
        return msg, kb
    else:
        return f"❌ <b>Out of stock in these ranges. Please try again later.</b>", {"inline_keyboard": [[{"text": "🔙 BACK", "callback_data": f"srv_{sid_short}", "icon_custom_emoji_id": "5438541186539232243", "style": "danger"}]]}

def handle_message(message):
    global waiting_for_firebase, current_db_mode, db_firebase, user_states, voltx_keys, force_join_channels, otp_forward_groups, otp_button_link, bot_settings
    if message.get("chat", {}).get("type") != "private": return
        
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    message_id = message["message_id"]
    first_name = message["from"].get("first_name", "User")

    if text == "🔙 BACK" and user_id == ADMIN_ID:
        send_message(chat_id, "❌ <b>Action Cancelled!</b>", reply_markup=get_main_keyboard(user_id)) 
        if user_id in user_states: del user_states[user_id]
        send_message(chat_id, get_owner_panel_text(), reply_markup=get_admin_inline_keyboard())
        return

    if not is_user_joined(user_id):
        fj_msg = (
            "<b>╔═════════════════════════╗</b>\n"
            "<b>║  🔥 CHANNEL ACCESS REQUIRED ║</b>\n"
            "<b>╚═════════════════════════╝</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b><tg-emoji emoji-id=\"5420517437885943844\">🔗</tg-emoji> Join all our official channels below to unlock full access to this bot.</b>\n\n"
            "<b><tg-emoji emoji-id=\"5352694861990501856\">✅</tg-emoji> After joining, click VERIFY JOINED.</b>"
        )
        send_message(chat_id, fj_msg, reply_markup=get_force_join_alert_keyboard())
        return

    is_new_user = (get_user(user_id) is None)
    add_user(user_id, first_name)
    user_data = get_user(user_id)

    if text.startswith("/start"):
        parts = text.split()
        if len(parts) > 1:
            param = parts[1]
            if param.startswith("alloc_"):
                try:
                    _, req_range, req_sid = param.split("_", 2)
                    last_req = user_cooldowns.get(user_id, 0)
                    now = time.time()
                    if now - last_req < bot_settings.get("cooldown", 0):
                        send_message(chat_id, f"⌛ <b>Please wait {int(bot_settings['cooldown'] - (now - last_req))} seconds before requesting again.</b>")
                        return
                    user_cooldowns[user_id] = now
                    wait_msg = send_message(chat_id, f"⏳ <b>Allocating instant number for {req_sid.title().replace('_', ' ')}...</b>")
                    msg, markup = get_number_allocation_content(req_sid, req_range, user_id=user_id)
                    if wait_msg and "result" in wait_msg:
                        edit_message(chat_id, wait_msg["result"]["message_id"], msg, reply_markup=markup)
                    else:
                        send_message(chat_id, msg, reply_markup=markup)
                    return
                except Exception: pass
            else:
                try:
                    inviter_id = int(param)
                    if is_new_user and inviter_id != user_id and get_user(inviter_id):
                        ref_amount = bot_settings.get("refer_reward", 0.2)
                        update_user_stats(inviter_id, ref_amount, 1)
                        send_message(inviter_id, f"🎉 <b>NEW REFERRAL JOINED!</b>\nSomeone joined using your invite link. You earned <code>+{ref_amount:.2f} BDT</code>.")
                except ValueError: pass
        
        start_msg = (
            "<b>╔═════════════════════════╗</b>\n"
            f"<b>  ✨ WELCOME TO PREMIUM OTP BOT</b>\n"
            "<b>╚═════════════════════════╝</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<blockquote>👋 <b>Hello, {html.escape(str(first_name))}!</b>\n\n"
            "🚀 <b>Fastest OTP Service:</b> Get instant virtual numbers with highest delivery speed.</blockquote>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "👇 <b>Select an option from menu below:</b>"
        )
        send_message(chat_id, start_msg, reply_markup=get_main_keyboard(user_id))
        
    elif text in ["⚡ GET NUMBER", "LIVE NUMBER"]:
        msg, markup = get_services_content()
        if markup: send_message(chat_id, msg, reply_markup=markup)
        else: send_message(chat_id, msg)
        
    elif text in ["📈 LIVE TRAFFIC", "LIVE TRAFFIC"]:
        msg, markup = get_live_traffic_content()
        send_message(chat_id, msg, reply_markup=markup)
            
    elif text in ["👥 INVITE FRIENDS", "INVITE FRIEND"]:
        invite_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        ref_reward = bot_settings.get("refer_reward", 0.2)
        msg = (
            "<b>╔═════════════════════════╗</b>\n"
            "<b>║  👥 REFERRAL PROGRAM  ║</b>\n"
            "<b>╚═════════════════════════╝</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<blockquote>🔗 <b>YOUR UNIQUE LINK:</b>\n<code>{invite_link}</code></blockquote>\n"
            f"<blockquote>🎁 <b>REWARD PER REFERRAL:</b> <code>{ref_reward:.2f} BDT</code></blockquote>\n"
            f"<blockquote>📊 <b>TOTAL FRIENDS INVITED:</b> <code>{user_data['total_invites']} Users</code></blockquote>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        send_message(chat_id, msg, reply_markup={"inline_keyboard": [[{"text": "📋 COPY INVITE LINK", "copy_text": {"text": invite_link}, "style": "success"}]]})
        
    elif text in ["💳 WALLET & PAY", "WALLET"]:
        wallet_txt = (
            "<b>╔═════════════════════════╗</b>\n"
            "<b>║   💳 YOUR DIGITAL WALLET ║</b>\n"
            "<b>╚═════════════════════════╝</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<blockquote>👤 <b>ACCOUNT NAME:</b> {html.escape(str(first_name))}</blockquote>\n"
            f"<blockquote>🆔 <b>ACCOUNT ID:</b> <code>{user_id}</code></blockquote>\n"
            f"<blockquote>💵 <b>AVAILABLE BALANCE:</b> <code>{user_data['balance']:.2f} BDT</code></blockquote>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>💳 WITHDRAWAL METHODS:</b>"
        )
        kb = {"inline_keyboard": []}
        for method in bot_settings.get("w_methods", []):
            kb["inline_keyboard"].append([{"text": f"💵 Withdraw via {method}", "callback_data": f"user_withdraw_{method}", "style": "primary"}])
        send_message(chat_id, wallet_txt, reply_markup=kb)
        
    elif text in ["🏆 LEADERBOARD", "LEADERBOARD"]:
        send_message(chat_id, get_leaderboard_text(), reply_markup={"inline_keyboard": [[{"text": "🔄 REFRESH LEADERBOARD", "callback_data": "refresh_leaderboard", "style": "success"}]]})

    elif text in ["👑 OWNER PANEL", "OWNER PANEL"]:
        if user_id == ADMIN_ID: send_message(chat_id, get_owner_panel_text(), reply_markup=get_admin_inline_keyboard())
        else: send_message(chat_id, "⚠️ <b>Access Denied! Reserved for Admin only.</b>")

def handle_callback(callback_query):
    global user_states, voltx_auto_mode, current_db_mode, force_join_status, force_join_channels, voltx_keys, otp_forward_groups, bot_settings
    query_id = callback_query["id"]
    user_id = callback_query["from"]["id"]
    data = callback_query["data"]
    chat_id = callback_query["message"]["chat"]["id"]
    message_id = callback_query["message"]["message_id"]

    if data == "check_fj_joined":
        if is_user_joined(user_id):
            delete_message(chat_id, message_id)
            send_message(chat_id, "✅ <b>Thank you for joining! Access unlocked successfully.</b>", reply_markup=get_main_keyboard(user_id))
        else: answer_callback_query(query_id, "❌ You haven't joined all channels yet!", show_alert=True)
        return

    if not is_user_joined(user_id):
        answer_callback_query(query_id, "Please join all required channels first!", show_alert=True)
        return

    if data == "refresh_traffic":
        msg, markup = get_live_traffic_content()
        edit_message(chat_id, message_id, msg, reply_markup=markup)
        answer_callback_query(query_id, "Traffic Refreshed!")
        return

    if data == "back_to_services":
        msg, markup = get_services_content()
        edit_message(chat_id, message_id, msg, reply_markup=markup)
        answer_callback_query(query_id)
        return

    if data.startswith("srv_"):
        sid_short = data[4:]
        msg, markup, err = get_countries_content(sid_short)
        if err: answer_callback_query(query_id, err, show_alert=True)
        else: edit_message(chat_id, message_id, msg, reply_markup=markup)
        return

    if data.startswith("cc_"):
        parts = data.split("_")
        sid_short = parts[1]
        c_code = parts[2]
        msg, markup = get_number_allocation_content(sid_short, c_code, user_id=user_id)
        edit_message(chat_id, message_id, msg, reply_markup=markup)
        return

    if data == "refresh_leaderboard":
        edit_message(chat_id, message_id, get_leaderboard_text(), reply_markup={"inline_keyboard": [[{"text": "🔄 REFRESH LEADERBOARD", "callback_data": "refresh_leaderboard", "style": "success"}]]})
        answer_callback_query(query_id, "Leaderboard Refreshed!")
        return

    if data == "close_panel":
        delete_message(chat_id, message_id)
        answer_callback_query(query_id)
        return

    if user_id != ADMIN_ID:
        answer_callback_query(query_id, "Access Denied!", show_alert=True)
        return

    # Admin Panel Callbacks
    if data == "manage_voltx":
        edit_message(chat_id, message_id, "🔑 <b>VOLTX KEY SYSTEM</b>\nManage API Keys below:", reply_markup={"inline_keyboard": [[{"text": "BACK", "callback_data": "back_to_admin", "style": "danger"}]]})
        answer_callback_query(query_id)
    elif data == "manage_fj":
        edit_message(chat_id, message_id, "🔗 <b>FORCE JOIN SYSTEM</b>\nManage channels below:", reply_markup={"inline_keyboard": [[{"text": "BACK", "callback_data": "back_to_admin", "style": "danger"}]]})
        answer_callback_query(query_id)
    elif data == "manage_otp_group":
        edit_message(chat_id, message_id, "🛡 <b>OTP GROUP MANAGEMENT</b>", reply_markup={"inline_keyboard": [[{"text": "BACK", "callback_data": "back_to_admin", "style": "danger"}]]})
        answer_callback_query(query_id)
    elif data == "dxa_control":
        edit_message(chat_id, message_id, "⚙️ <b>DXA CONTROL PANEL</b>", reply_markup={"inline_keyboard": [[{"text": "BACK", "callback_data": "back_to_admin", "style": "danger"}]]})
        answer_callback_query(query_id)
    elif data == "broadcast_menu":
        edit_message(chat_id, message_id, "📣 <b>BROADCAST SYSTEM</b>", reply_markup={"inline_keyboard": [[{"text": "BACK", "callback_data": "back_to_admin", "style": "danger"}]]})
        answer_callback_query(query_id)
    elif data == "upload_firebase":
        edit_message(chat_id, message_id, "🔥 <b>FIREBASE JSON UPLOAD</b>", reply_markup={"inline_keyboard": [[{"text": "BACK", "callback_data": "back_to_admin", "style": "danger"}]]})
        answer_callback_query(query_id)
    elif data == "user_control":
        edit_message(chat_id, message_id, "👤 <b>USER CONTROL PANEL</b>", reply_markup={"inline_keyboard": [[{"text": "BACK", "callback_data": "back_to_admin", "style": "danger"}]]})
        answer_callback_query(query_id)
    elif data == "db_status":
        answer_callback_query(query_id, f"Current DB: {current_db_mode.upper()}", show_alert=True)
    elif data == "back_to_admin":
        edit_message(chat_id, message_id, get_owner_panel_text(), reply_markup=get_admin_inline_keyboard())
        answer_callback_query(query_id)

def main():
    load_local_data()
    init_sqlite()
    init_firebase_from_file()
    
    global BOT_USERNAME
    BOT_USERNAME = get_bot_info()
    set_bot_commands()
    
    threading.Thread(target=voltx_console_listener, daemon=True).start()
    threading.Thread(target=voltx_sms_listener, daemon=True).start()
    threading.Thread(target=auto_cache_menu_thread, daemon=True).start()
    
    print(f"Bot @{BOT_USERNAME} is running in Ultra-Premium Mode...")
    
    offset = None
    while True:
        try:
            url = BASE_URL + "getUpdates"
            res = requests.get(url, params={"timeout": 30, "offset": offset}).json()
            if res.get("ok"):
                for update in res["result"]:
                    offset = update["update_id"] + 1
                    if "message" in update: 
                        threading.Thread(target=handle_message, args=(update["message"],)).start()
                    elif "callback_query" in update: 
                        threading.Thread(target=handle_callback, args=(update["callback_query"],)).start()
        except Exception:
            time.sleep(3)

if __name__ == "__main__":
    main()