import telebot
from telebot import types
import sqlite3
import random
import time

# ==================== НАСТРОЙКИ ====================
TOKEN = "8226623341:AAGCmnR-gOx7EBsrdeLhY5RnO3Wl3O19MOg"
ADMIN_ID = 6151671553
START_BALANCE = 1000
BONUS_AMOUNT = 100
BONUS_COOLDOWN = 30 * 60  # 30 минут
FIELD_SIZE = 25  # 5x5

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# ==================== БАЗА ДАННЫХ ====================
conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute(f"""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT {START_BALANCE},
    last_bonus INTEGER DEFAULT 0
)
""")

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
    text = "🎮 Доступные команды:\n"
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

# ==================== АДМИН И ПЕРЕВОД ====================
@bot.message_handler(commands=["minadd"])
def minadd(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        return
    try:
        args = message.text.split()
        target_username = args[1].replace("@", "")
        amount = int(args[2])
    except:
        bot.reply_to(message, "Использование: /minadd @username сумма")
        return
    cursor.execute("SELECT user_id, username FROM users WHERE username=?", (target_username,))
    user = cursor.fetchone()
    if not user:
        bot.reply_to(message, "Пользователь не найден")
        return
    target_id = user[0]
    target_first = target_username
    update_balance(target_id, amount)
    bot.send_message(message.chat.id, f"👑 Пользователю {format_user_mention(target_id, target_username, target_first)} выдано {amount} монет.")

@bot.message_handler(commands=["мперевод"])
def mpererod(message):
    try:
        args = message.text.split()
        target_username = args[1].replace("@", "")
        amount = int(args[2])
    except:
        bot.reply_to(message, "Использование: /мперевод @username сумма")
        return
    sender_id = message.from_user.id
    sender_username = message.from_user.username
    sender_first = message.from_user.first_name
    get_user(sender_id, sender_username)
    sender_balance = get_user(sender_id)[2]
    if amount <= 0 or amount > sender_balance:
        bot.reply_to(message, f"Неверная сумма! Ваш баланс: {sender_balance}")
        return
    cursor.execute("SELECT user_id, username FROM users WHERE username=?", (target_username,))
    user = cursor.fetchone()
    if not user:
        bot.reply_to(message, "Пользователь не найден")
        return
    target_id = user[0]
    target_first = target_username
    update_balance(sender_id, -amount)
    update_balance(target_id, amount)
    bot.send_message(message.chat.id, f"🪙 {format_user_mention(sender_id, sender_username, sender_first)} перевел пользователю {format_user_mention(target_id, target_username, target_first)} {amount} монет.")

# ==================== ИГРА ====================
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

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    user_id = message.from_user.id
    text = message.text.strip()
    username = message.from_user.username
    first_name = message.from_user.first_name
    get_user(user_id, username)

    if user_id in user_states and user_states[user_id].get("state") == "waiting_for_bet":
        if not text.isdigit():
            return
        bet = int(text)
        user = get_user(user_id)
        balance = user[2]
        if bet <= 0 or bet > balance:
            bot.send_message(message.chat.id, f"⚠ {format_user_mention(user_id, username, first_name)}, ставка некорректна или больше баланса ({balance} монет).")
            return
        update_balance(user_id, -bet)
        try:
            bot.delete_message(message.chat.id, user_states[user_id]["msg_id"])
        except:
            pass
        # Кнопки выбора мин в один ряд
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("3", callback_data=f"mines_3_{bet}"),
            types.InlineKeyboardButton("5", callback_data=f"mines_5_{bet}"),
            types.InlineKeyboardButton("10", callback_data=f"mines_10_{bet}"),
            types.InlineKeyboardButton("24", callback_data=f"mines_24_{bet}")
        )
        msg = bot.send_message(message.chat.id, "📃 Выберите количество мин на поле:", reply_markup=markup)
        user_states[user_id]["state"] = "waiting_for_mines"
        user_states[user_id]["msg_id"] = msg.message_id
        user_states[user_id]["data"]["bet"] = bet

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

    if state == "waiting_for_mines" and data.startswith("mines_"):
        _, mines_count, bet = data.split("_")
        mines_count = int(mines_count)
        bet = int(bet)
        try:
            bot.delete_message(call.message.chat.id, user_states[user_id]["msg_id"])
        except:
            pass
        all_cells = list(range(FIELD_SIZE))
        mine_cells = random.sample(all_cells, mines_count)
        user_data.update({"mines": mine_cells, "opened": [], "multiplier":1.0})
        # Поле 5x5 пустых кнопок
        markup = types.InlineKeyboardMarkup()
        for row in range(5):
            buttons = []
            for col in range(5):
                index = row*5 + col
                buttons.append(types.InlineKeyboardButton(" ", callback_data=f"cell_{index}"))
            markup.row(*buttons)
        btn_cashout = types.InlineKeyboardButton("💰 Забрать", callback_data="cashout")
        markup.add(btn_cashout)
        msg = bot.send_message(call.message.chat.id, "💣 Игра началась, выбирайте клетку:", reply_markup=markup)
        user_states[user_id]["state"] = "playing"
        user_states[user_id]["msg_id"] = msg.message_id
        user_data.update({"bet": bet, "mine_count": mines_count})
        return

    if state == "playing":
        if data.startswith("cell_"):
            cell_index = int(data.split("_")[1])
            if cell_index in user_data["opened"]:
                bot.answer_callback_query(call.id, "Эта клетка уже открыта!")
                return
            if cell_index in user_data["mines"]:
                # Показываем все поле с минами и безопасными клетками
                markup = types.InlineKeyboardMarkup()
                for row in range(5):
                    buttons = []
                    for col in range(5):
                        index = row*5 + col
                        if index in user_data["mines"]:
                            buttons.append(types.InlineKeyboardButton("💣", callback_data="disabled"))
                        else:
                            buttons.append(types.InlineKeyboardButton("✅", callback_data="disabled"))
                    markup.row(*buttons)
                text = f"💥 Игра завершена.\n{format_user_mention(user_id, username, first_name)} проиграл {user_data['bet']} монет."
                try:
                    bot.edit_message_text(chat_id=call.message.chat.id, message_id=user_states[user_id]["msg_id"], text=text, reply_markup=markup)
                except:
                    pass
                user_states.pop(user_id)
            else:
                user_data["opened"].append(cell_index)
                opened_count = len(user_data["opened"])
                multiplier = calculate_multiplier(user_data["mine_count"], opened_count)
                user_data["multiplier"] = multiplier
                markup = types.InlineKeyboardMarkup()
                for row in range(5):
                    buttons = []
                    for col in range(5):
                        index = row*5 + col
                        if index in user_data["opened"]:
                            buttons.append(types.InlineKeyboardButton("✅", callback_data=f"cell_{index}"))
                        else:
                            buttons.append(types.InlineKeyboardButton(" ", callback_data=f"cell_{index}"))
                    markup.row(*buttons)
                btn_cashout = types.InlineKeyboardButton("💰 Забрать", callback_data="cashout")
                markup.add(btn_cashout)
                try:
                    bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=user_states[user_id]["msg_id"], reply_markup=markup)
                except:
                    pass
                if opened_count == FIELD_SIZE - user_data["mine_count"]:
                    win_amount = round(user_data["bet"] * multiplier)
                    update_balance(user_id, win_amount)
                    text = f"💎 Игра завершилась.\n{format_user_mention(user_id, username, first_name)} открыл все поле, не попав ни на одну мину и выиграл {win_amount} монет!"
                    try:
                        bot.edit_message_text(chat_id=call.message.chat.id, message_id=user_states[user_id]["msg_id"], text=text)
                    except:
                        pass
                    user_states.pop(user_id)
        elif data == "cashout":
            opened_count = len(user_data["opened"])
            multiplier = user_data["multiplier"]
            win_amount = round(user_data["bet"] * multiplier)
            update_balance(user_id, win_amount)
            text = f"💠 Игра завершилась.\n{format_user_mention(user_id, username, first_name)} сделал кэшаут и забрал {win_amount} монет."
            try:
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=user_states[user_id]["msg_id"], text=text)
            except:
                pass
            user_states.pop(user_id)
        bot.answer_callback_query(call.id)

# ==================== ЗАПУСК ====================
print("Бот запущен...")
bot.infinity_polling()