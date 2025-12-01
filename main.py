# bot.py
import asyncio
import logging
import os
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# === НАСТРОЙКИ ===
TOKEN = "8410854623:AAFbxvsnACtVNhx90UMQSlnKQJom5jbaa3E"  # Ваш токен
ADMIN_ID = 0  # если нужен админ — укажите свой TG ID

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
logging.basicConfig(level=logging.INFO)

# === БАЗА ДАННЫХ ===
DB_NAME = "freelance_bot.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            role TEXT CHECK(role IN ('customer', 'worker')),
            name TEXT,
            username TEXT,
            skills TEXT,
            experience TEXT,
            portfolio TEXT,
            contact TEXT
        )
    ''')
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            files TEXT, -- JSON list of file_id
            price REAL,
            complexity TEXT CHECK(complexity IN ('легкий','средний','сложный')),
            customer_id INTEGER,
            worker_id INTEGER,
            pending_worker_id INTEGER,
            status TEXT CHECK(status IN ('active','taken','completed')) DEFAULT 'active',
            FOREIGN KEY(customer_id) REFERENCES users(id)
        )
    ''')
    conn.commit()
    conn.close()

# === СОСТОЯНИЯ FSM ===
class RegisterStates(StatesGroup):
    role = State()
    name = State()
    contact = State()
    skills = State()
    experience = State()
    portfolio = State()

class OrderStates(StatesGroup):
    title = State()
    description = State()
    files = State()
    price = State()
    complexity = State()

# === КЛАВИАТУРЫ ===
def main_menu(role: str):
    kb = [
        [types.KeyboardButton(text="📝 Разместить заказ"), types.KeyboardButton(text="👤 Смотреть исполнителей")],
        [types.KeyboardButton(text="📂 Мои заказы"), types.KeyboardButton(text="⚙️ Профиль")],
    ]
    if role == "worker":
        kb = [
            [types.KeyboardButton(text="📄 Биржа заказов")],
            [types.KeyboardButton(text="📂 Мои отклики / Заказы"), types.KeyboardButton(text="⚙️ Профиль")],
        ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def role_keyboard():
    return types.ReplyKeyboardMarkup(keyboard=[
        [types.KeyboardButton(text="Заказчик"), types.KeyboardButton(text="Исполнитель")]
    ], resize_keyboard=True, one_time_keyboard=True)

def complexity_keyboard():
    return types.ReplyKeyboardMarkup(keyboard=[
        [types.KeyboardButton(text="легкий"), types.KeyboardButton(text="средний"), types.KeyboardButton(text="сложный")]
    ], resize_keyboard=True, one_time_keyboard=True)

# === УТИЛИТЫ ===
def get_user(tg_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (tg_id,))
    row = cur.fetchone()
    conn.close()
    return row

def is_registered(tg_id: int) -> bool:
    return get_user(tg_id) is not None

def auto_complexity(text: str) -> str:
    text = text.lower()
    if any(w in text for w in ["просто", "легко", "быстро", "маленький", "новичок"]):
        return "легкий"
    if any(w in text for w in ["сложно", "большой", "долго", "профессионал", "сложная"]):
        return "сложный"
    return "средний"

# === ХЕНДЛЕРЫ ===
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if user:
        role = user[1]
        await message.answer(
            f"С возвращением, <b>{user[2] or message.from_user.full_name}</b>!\nРоль: { 'Заказчик' if role == 'customer' else 'Исполнитель' }",
            reply_markup=main_menu(role)
        )
    else:
        await message.answer(
            "Привет! Это фриланс-биржа в Telegram.\nВыберите роль:",
            reply_markup=role_keyboard()
        )
        await state.set_state(RegisterStates.role)

# === РЕГИСТРАЦИЯ ===
@dp.message(RegisterStates.role)
async def reg_role(message: types.Message, state: FSMContext):
    if message.text not in ["Заказчик", "Исполнитель"]:
        await message.answer("Выберите роль кнопкой ниже!")
        return
    role = "customer" if message.text == "Заказчик" else "worker"
    await state.update_data(role=role)
    await message.answer("Введите ваше имя (как представить вас):")
    await state.set_state(RegisterStates.name)

@dp.message(RegisterStates.name)
async def reg_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer(f"Имя: {message.text}\nТеперь укажите контакт для связи (email или @username):")
    await state.set_state(RegisterStates.contact)

@dp.message(RegisterStates.contact)
async def reg_contact(message: types.Message, state: FSMContext):
    await state.update_data(contact=message.text.strip())
    data = await state.get_data()
    if data["role"] == "worker":
        await message.answer("Укажите ваши навыки (через запятую):")
        await state.set_state(RegisterStates.skills)
    else:
        await finish_registration(message, state)

@dp.message(RegisterStates.skills)
async def reg_skills(message: types.Message, state: FSMContext):
    await state.update_data(skills=message.text.strip())
    await message.answer("Опишите опыт работы (лет/проекты):")
    await state.set_state(RegisterStates.experience)

@dp.message(RegisterStates.experience)
async def reg_experience(message: types.Message, state: FSMContext):
    await state.update_data(experience=message.text.strip())
    await message.answer("Портфолио (ссылки, описание, примеры):")
    await state.set_state(RegisterStates.portfolio)

@dp.message(RegisterStates.portfolio)
async def reg_portfolio(message: types.Message, state: FSMContext):
    await state.update_data(portfolio=message.text.strip())
    await finish_registration(message, state)

async def finish_registration(message: types.Message, state: FSMContext):
    data = await state.get_data()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO users (id, role, name, username, contact, skills, experience, portfolio)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        message.from_user.id,
        data["role"],
        data.get("name"),
        message.from_user.username,
        data.get("contact"),
        data.get("skills"),
        data.get("experience"),
        data.get("portfolio")
    ))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer(
        "Регистрация завершена! 🎉",
        reply_markup=main_menu(data["role"])
    )

# === ЗАКАЗЧИК: Разместить заказ ===
@dp.message(F.text == "📝 Разместить заказ")
async def new_order_start(message: types.Message, state: FSMContext):
    if get_user(message.from_user.id)[1] != "customer":
        return
    await message.answer("Введите название заказа:")
    await state.set_state(OrderStates.title)

@dp.message(OrderStates.title)
async def order_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Опишите задачу подробно:")
    await state.set_state(OrderStates.description)

@dp.message(OrderStates.description)
async def order_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("Пришлите файлы (если есть). После всех — нажмите кнопку ниже.", 
                         reply_markup=types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="Пропустить файлы")]], resize_keyboard=True))
    await state.set_state(OrderStates.files)

@dp.message(F.text == "Пропустить файлы")
@dp.message(OrderStates.files, F.document | F.photo)
async def order_files(message: types.Message, state: FSMContext):
    data = await state.get_data()
    files = data.get("files", [])
    if message.document:
        files.append(message.document.file_id)
    elif message.photo:
        files.append(message.photo[-1].file_id)
    await state.update_data(files=files)
    if not message.text == "Пропустить файлы":
        await message.answer("Файл добавлен. Можете отправить ещё или нажать «Пропустить файлы»")
        return
    await message.answer("Укажите бюджет (в рублях, только число):")
    await state.set_state(OrderStates.price)

@dp.message(OrderStates.price)
async def order_price(message: types.Message, state: FSMContext):
    if not message.text.replace('.', '').isdigit():
        await message.answer("Введите число!")
        return
    await state.update_data(price=float(message.text))
    await message.answer("Выберите сложность или я определю автоматически:", reply_markup=complexity_keyboard())
    await state.set_state(OrderStates.complexity)

@dp.message(OrderStates.complexity)
async def order_complexity(message: types.Message, state: FSMContext):
    data = await state.get_data()
    complexity = message.text if message.text in ["легкий","средний","сложный"] else auto_complexity(data["description"])
    
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO orders (title, description, files, price, complexity, customer_id, status)
        VALUES (?, ?, ?, ?, ?, ?, 'active')
    ''', (
        data["title"],
        data["description"],
        ",".join(data.get("files", [])),
        data["price"],
        complexity,
        message.from_user.id
    ))
    order_id = cur.lastrowid
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"Заказ #{order_id} опубликован!\nСложность: {complexity}", reply_markup=main_menu("customer"))

# === БИРЖА ЗАКАЗОВ ===
@dp.message(F.text == "📄 Биржа заказов")
async def market(message: types.Message):
    if get_user(message.from_user.id)[1] != "worker":
        return
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, title, price, complexity FROM orders WHERE status = 'active'")
    orders = cur.fetchall()
    conn.close()
    
    if not orders:
        await message.answer("Активных заказов пока нет.")
        return
    
    for oid, title, price, comp in orders:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Откликнуться", callback_data=f"apply_{oid}")]])
        await message.answer(f"<b>Заказ #{oid}</b>\n{title}\n💰 {price} ₽\nСложность: {comp}", reply_markup=kb)

# === ОТКЛИК ===
@dp.callback_query(lambda c: c.data.startswith("apply_"))
async def apply_order(call: types.CallbackQuery):
    order_id = int(call.data.split("_")[1])
    worker_id = call.from_user.id
    
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT customer_id, pending_worker_id FROM orders WHERE id = ?", (order_id,))
    row = cur.fetchone()
    if not row or row[1] is not None:  # уже кто-то откликнулся
        await call.answer("Кто-то уже откликнулся раньше!")
        conn.close()
        return
    
    cur.execute("UPDATE orders SET pending_worker_id = ? WHERE id = ?", (worker_id, order_id))
    conn.commit()
    
    # Уведомляем заказчика
    customer_id = row[0]
    worker = get_user(worker_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подтвердить исполнителя", callback_data=f"confirm_{order_id}_{worker_id}")]
    ])
    await bot.send_message(customer_id, f"""
Новый отклик на ваш заказ #{order_id}!

Исполнитель: <b>{worker[2]}</b> @{worker[3]}
Навыки: {worker[4]}
Опыт: {worker[5]}
Портфолио: {worker[6]}
Контакт: {worker[7]}
    """, reply_markup=kb)
    
    await call.answer("Отклик отправлен!")
    conn.close()

# === ПОДТВЕРЖДЕНИЕ ===
@dp.callback_query(lambda c: c.data.startswith("confirm_"))
async def confirm_worker(call: types.CallbackQuery):
    _, order_id, worker_id = call.data.split("_")
    order_id = int(order_id)
    worker_id = int(worker_id)
    
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE orders SET worker_id = ?, pending_worker_id = NULL, status = 'taken' WHERE id = ?", (worker_id, order_id))
    conn.commit()
    conn.close()
    
    # Уведомляем исполнителя
    customer = get_user(call.from_user.id)
    await bot.send_message(worker_id, f"""
Ваш отклик подтверждён!

Заказчик: <b>{customer[2]}</b> @{customer[3]}
Контакт заказчика: {customer[7]}

Теперь вы можете связаться напрямую.
    """)
    
    await call.answer("Исполнитель подтверждён!")
    await call.message.edit_text(call.message.text + "\n\n✅ Исполнитель подтверждён!")

# === ПРОСМОТР ИСПОЛНИТЕЛЕЙ (ЗАКАЗЧИК) ===
@dp.message(F.text == "👤 Смотреть исполнителей")
async def list_workers(message: types.Message):
    if get_user(message.from_user.id)[1] != "customer":
        return
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT name, username, skills, experience, portfolio, contact FROM users WHERE role = 'worker'")
    workers = cur.fetchall()
    conn.close()
    
    if not workers:
        await message.answer("Пока нет зарегистрированных исполнителей.")
        return
    
    for name, username, skills, exp, port, contact in workers:
        await message.answer(f"""
<b>{name}</b> @{username}
Навыки: {skills or 'Не указано'}
Опыт: {exp or 'Не указано'}
Портфолио: {port or 'Не указано'}
Контакт: {contact or 'Не указано'}

Можете связаться напрямую через @{username}
        """)

# === МОИ ЗАКАЗЫ (ЗАКАЗЧИК) ===
@dp.message(F.text == "📂 Мои заказы")
async def my_orders_customer(message: types.Message):
    if get_user(message.from_user.id)[1] != "customer":
        return
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT o.id, o.title, o.status, u.name, u.username 
        FROM orders o 
        LEFT JOIN users u ON o.worker_id = u.id 
        WHERE o.customer_id = ?
    """, (user_id,))
    orders = cur.fetchall()
    conn.close()
    
    if not orders:
        await message.answer("У вас пока нет заказов.")
        return
    
    for oid, title, status, w_name, w_username in orders:
        worker_info = f"Исполнитель: {w_name} @{w_username}" if w_name else "Нет исполнителя"
        await message.answer(f"""
<b>Заказ #{oid}</b>: {title}
Статус: {status}
{worker_info}
        """)

# === МОИ ОТКЛИКИ / ЗАКАЗЫ (ИСПОЛНИТЕЛЬ) ===
@dp.message(F.text == "📂 Мои отклики / Заказы")
async def my_orders_worker(message: types.Message):
    if get_user(message.from_user.id)[1] != "worker":
        return
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    # Отклики (pending)
    cur.execute("""
        SELECT o.id, o.title, o.status, u.name, u.username 
        FROM orders o 
        JOIN users u ON o.customer_id = u.id 
        WHERE o.pending_worker_id = ?
    """, (user_id,))
    pending = cur.fetchall()
    
    # Взятые (taken)
    cur.execute("""
        SELECT o.id, o.title, o.status, u.name, u.username 
        FROM orders o 
        JOIN users u ON o.customer_id = u.id 
        WHERE o.worker_id = ? AND o.status = 'taken'
    """, (user_id,))
    taken = cur.fetchall()
    conn.close()
    
    response = ""
    if pending:
        response += "<b>Ваши отклики (ожидают подтверждения):</b>\n"
        for oid, title, status, c_name, c_username in pending:
            response += f"#{oid}: {title} (Заказчик: {c_name} @{c_username})\n"
    
    if taken:
        response += "\n<b>Взятые заказы:</b>\n"
        for oid, title, status, c_name, c_username in taken:
            response += f"#{oid}: {title} (Заказчик: {c_name} @{c_username})\n"
    
    if not response:
        response = "У вас пока нет откликов или заказов."
    
    await message.answer(response)

# === ПРОФИЛЬ (ОБЩИЙ ДЛЯ ВСЕХ) ===
@dp.message(F.text == "⚙️ Профиль")
async def profile(message: types.Message):
    user = get_user(message.from_user.id)
    if not user:
        return
    role = "Заказчик" if user[1] == "customer" else "Исполнитель"
    skills = f"Навыки: {user[4] or 'Не указано'}\n" if user[1] == "worker" else ""
    exp = f"Опыт: {user[5] or 'Не указано'}\n" if user[1] == "worker" else ""
    port = f"Портфолио: {user[6] or 'Не указано'}\n" if user[1] == "worker" else ""
    
    await message.answer(f"""
<b>Ваш профиль</b>
Роль: {role}
Имя: {user[2]}
@username: @{user[3]}
Контакт: {user[7] or 'Не указано'}
{skills}{exp}{port}
    """)

# === ЗАПУСК ===
async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())