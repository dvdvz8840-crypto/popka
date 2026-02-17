import telebot
from telebot import types
import sqlite3
import random
import time
import os

# ==================== НАСТРОЙКИ ====================
TOKEN = "8226623341:AAGCmnR-gOx7EBsrdeLhY5RnO3Wl3O19MOg"  # лучше через env для продакшена
ADMIN_ID = 6151671553
START_BALANCE = 1000
BONUS_AMOUNT = 100
BONUS_COOLDOWN = 30 * 60  # 30 минут
FIELD_SIZE = 25  # 5x5
SAFE_ROWS = 5

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# ==================== БАЗА ДАННЫХ ====================
conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT ?,
    last_bonus INTEGER DEFAULT 0
)
""", (START_BALANCE,))

cursor.execute("""
CREATE TABLE IF NOT EXISTS games (
    user_id INTEGER PRIMARY KEY,
    bet INTEGER,
    mines TEXT,
    opened TEXT,
    multiplier REAL,
    active INTEGER
)
""")
conn.commit()

# ==================== СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЕЙ ====================
user_states = {}  # user_id: {"state": str, "data": {}}

# ==================== ХЕЛПЕРЫ ====================
def get_user(user_id, username=None):
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users (user_id, username, balance) VALUES (?, ?, ?)",
                       (user_id, username, START_BALANCE))
        conn.commit()
        return (user_id, username, START_BALANCE, 0)
    return user

def update_balance(user_id, amount):
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
    conn.commit()

def format_user_mention(user_id, username, first_name):
    if username:
        return f'<a href="https://t.me/{username}">{first_name}</a>'
    return f'<a href="tg://user?id={user_id}">{first_name}</a>'

def calculate_multiplier(mines_count, opened_count):
    safe_cells = FIELD_SIZE - mines_count
    return round(1 + (opened_count / safe_cells) * (mines_count + 1), 2)

# ==================== КОМАНДЫ ====================
@bot.message_handler(commands=["minfo"])
def minfo(message):
    text = "🎮 Доступные команды бота:\n\n"
    text += "/mina      — Начать игру в мины\n"
    text += "/minbonus  — Получить бонус (раз в 30 минут)\n"
    text += "/minb      — Показать баланс\n"
    text += "/мперевод  — Перевести монеты другому игроку\n"
    text += "/minfo     — Список всех команд"
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=["minb"])
def minb(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    user = get_user(user_id, username)
    balance = user[2]
    bot.send_message(message.chat.id, f"💰 Баланс {format_user_mention(user_id, username, first_name)}: {balance} монет")

@bot.message_handler(commands=["minbonus"])
def minbonus(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    user = get_user(user_id, username)
    now = int(time.time())
    last_bonus = user[3]
    if now - last_bonus >= BONUS_COOLDOWN:
        update_balance(user_id, BONUS_AMOUNT)
        cursor.execute("UPDATE users SET last_bonus=? WHERE user_id=?", (now, user_id))
        conn.commit()
        bot.send_message(message.chat.id, f"🎁 {format_user_mention(user_id, username, first_name)} получил бонус в размере {BONUS_AMOUNT} монет!")
    else:
        remaining = BONUS_COOLDOWN - (now - last_bonus)
        minutes = remaining // 60
        seconds = remaining % 60
        bot.send_message(message.chat.id, f"🕒 {format_user_mention(user_id, username, first_name)} бонус можно снова получить через {minutes}м {seconds}с.")

@bot.message_handler(commands=["mina"])
def mina(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    get_user(user_id, username)
    if user_id in user_states and user_states[user_id].get("state") == "playing":
        bot.send_message(message.chat.id, "⚠ У вас уже активная игра!")
        return
    msg = bot.send_message(message.chat.id, "💣 Напишите вашу ставку в чат:")
    user_states[user_id] = {"state": "waiting_for_bet", "msg_id": msg.message_id, "data": {}}

# ==================== ОБРАБОТКА СООБЩЕНИЙ ====================
@bot.message_handler(func=lambda m: True)
def handle_text(message):
    user_id = message.from_user.id
    text = message.text.strip()
    username = message.from_user.username
    first_name = message.from_user.first_name
    get_user(user_id, username)
    
    # ==== Ставка ====
    if user_id in user_states and user_states[user_id].get("state") == "waiting_for_bet":
        if not text.isdigit():
            return  # игнорируем слова
        bet = int(text)
        user = get_user(user_id)
        balance = user[2]
        if bet <= 0 or bet > balance:
            bot.send_message(message.chat.id, f"⚠ {format_user_mention(user_id, username, first_name)}, ставка некорректна или больше баланса ({balance} монет).")
            return
        update_balance(user_id, -bet)
        try: bot.delete_message(message.chat.id, user_states[user_id]["msg_id"])
        except: pass
        # Выбор мин
        markup = types.InlineKeyboardMarkup(row_width=4)
        for m in [3,5,10,24]:
            btn = types.InlineKeyboardButton(str(m), callback_data=f"mines_{m}_{bet}")
            markup.add(btn)
        msg = bot.send_message(message.chat.id, "📃 Выберите количество мин на поле:", reply_markup=markup)
        user_states[user_id]["state"] = "waiting_for_mines"
        user_states[user_id]["msg_id"] = msg.message_id
        user_states[user_id]["data"]["bet"] = bet

# ==================== CALLBACKS ====================
@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    user_id = call.from_user.id
    username = call.from_user.username
    first_name = call.from_user.first_name
    data = call.data
    
    if user_id not in user_states:
        bot.answer_callback_query(call.id, "⛔ Эта игра не ваша.")
        return
    
    state = user_states[user_id].get("state")
    user_data = user_states[user_id].get("data", {})
    
    # ==== Выбор мин ====
    if state == "waiting_for_mines" and data.startswith("mines_"):
        _, mines_count, bet = data.split("_")
        mines_count = int(mines_count)
        bet = int(bet)
        try: bot.delete_message(call.message.chat.id, user_states[user_id]["msg_id"])
        except: pass
        all_cells = list(range(FIELD_SIZE))
        mine_cells = random.sample(all_cells, mines_count)
        user_data.update({"mines": mine_cells, "opened": [], "multiplier":1.0})
        # Создаем поле
        markup = types.InlineKeyboardMarkup(row_width=5)
        for i in range(FIELD_SIZE):
            btn = types.InlineKeyboardButton("⬜", callback_data=f"cell_{i}")
            markup.add(btn)
        btn_cashout = types.InlineKeyboardButton("💰 Забрать", callback_data="cashout")
        markup.add(btn_cashout)
        msg = bot.send_message(call.message.chat.id, "💣 Игра началась, выбирайте клетку:", reply_markup=markup)
        user_states[user_id]["state"] = "playing"
        user_states[user_id]["msg_id"] = msg.message_id
        user_data.update({"bet": bet, "mine_count": mines_count})
        return

    # ==== Игровые действия ====
    if state == "playing":
        if data.startswith("cell_"):
            cell_index = int(data.split("_")[1])
            if cell_index in user_data["opened"]:
                bot.answer_callback_query(call.id, "Эта клетка уже открыта!")
                return
            if cell_index in user_data["mines"]:
                text = f"💥 Игра завершена.\n{format_user_mention(user_id, username, first_name)} проиграл {user_data['bet']} монет."
                try: bot.edit_message_text(chat_id=call.message.chat.id, message_id=user_states[user_id]["msg_id"], text=text)
                user_states.pop(user_id)
            else:
                user_data["opened"].append(cell_index)
                opened_count = len(user_data["opened"])
                multiplier = calculate_multiplier(user_data["mine_count"], opened_count)
                user_data["multiplier"] = multiplier
                # Обновляем поле
                markup = types.InlineKeyboardMarkup(row_width=5)
                for i in range(FIELD_SIZE):
                    if i in user_data["opened"]:
                        btn = types.InlineKeyboardButton("✅", callback_data=f"cell_{i}")
                    else:
                        btn = types.InlineKeyboardButton("⬜", callback_data=f"cell_{i}")
                    markup.add(btn)
                btn_cashout = types.InlineKeyboardButton("💰 Забрать", callback_data="cashout")
                markup.add(btn_cashout)
                try: bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=user_states[user_id]["msg_id"], reply_markup=markup)
                # Проверка выигрыша всех безопасных клеток
                if opened_count == FIELD_SIZE - user_data["mine_count"]:
                    win_amount = round(user_data["bet"] * multiplier)
                    update_balance(user_id, win_amount)
                    text = f"💎 Игра завершилась.\n{format_user_mention(user_id, username, first_name)} открыл все поле, не попав ни на одну мину и выиграл {win_amount} монет!"
                    try: bot.edit_message_text(chat_id=call.message.chat.id, message_id=user_states[user_id]["msg_id"], text=text)
                    user_states.pop(user_id)
        elif data == "cashout":
            opened_count = len(user_data["opened"])
            multiplier = user_data["multiplier"]
            win_amount = round(user_data["bet"] * multiplier)
            update_balance(user_id, win_amount)
            text = f"💠 Игра завершилась.\n{format_user_mention(user_id, username, first_name)} сделал кэшаут и забрал {win_amount} монет."
            try: bot.edit_message_text(chat_id=call.message.chat.id, message_id=user_states[user_id]["msg_id"], text=text)
            user_states.pop(user_id)
        bot.answer_callback_query(call.id)

# ==================== РУН ====================
print("Бот запущен...")
bot.infinity_polling()