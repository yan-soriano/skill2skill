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

# === АНТИ-СПАМ И ЛИМИТЫ ===
MAX_TITLE_LEN = 100
MIN_TITLE_LEN = 10
MAX_DESC_LEN = 2000
MIN_DESC_LEN = 50
MAX_SKILLS_LEN = 300
MIN_SKILLS_LEN = 10
MAX_EXP_LEN = 1000
MIN_EXP_LEN = 50
MAX_PORT_LEN = 1000
MIN_PORT_LEN = 50

SPAM_WORDS = ["куплю", "продам", "реклама", "спам", "http", "https", "www"]  # Добавь свои слова для блокировки

ORDER_COOLDOWN = 600  # 10 минут в секундах
PROFILE_COOLDOWN = 1800  # 30 минут в секундах

# Для хранения времени последнего действия
from datetime import datetime
user_last_order = {}  # {user_id: timestamp}
user_last_profile = {}  # {user_id: timestamp}

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
            status TEXT CHECK(status IN ('active','taken','completed')) DEFAULT 'active',
            FOREIGN KEY(customer_id) REFERENCES users(id)
        )
    ''')
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            worker_id INTEGER,
            status TEXT DEFAULT 'pending',  -- pending / accepted / rejected
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(order_id) REFERENCES orders(id),
            FOREIGN KEY(worker_id) REFERENCES users(id),
            UNIQUE(order_id, worker_id)
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
    skills = message.text.strip()
    if len(skills) < MIN_SKILLS_LEN or len(skills) > MAX_SKILLS_LEN:
        await message.answer(f"Навыки должны быть от {MIN_SKILLS_LEN} до {MAX_SKILLS_LEN} символов!\nТекущее количество: {len(skills)}")
        return
    if any(word in skills.lower() for word in SPAM_WORDS):
        await message.answer("В навыках запрещены рекламные слова и ссылки!")
        return
    
    await state.update_data(skills=skills)
    await message.answer("Опишите опыт работы (лет/проекты):")
    await state.set_state(RegisterStates.experience)


@dp.message(RegisterStates.experience)
async def reg_experience(message: types.Message, state: FSMContext):
    experience = message.text.strip()
    if len(experience) < MIN_EXP_LEN or len(experience) > MAX_EXP_LEN:
        await message.answer(f"Опыт должен быть от {MIN_EXP_LEN} до {MAX_EXP_LEN} символов!\nСейчас: {len(experience)}")
        return
    if any(word in experience.lower() for word in SPAM_WORDS):
        await message.answer("В описании опыта запрещены рекламные слова и ссылки!")
        return
    
    await state.update_data(experience=experience)
    await message.answer("Портфолио (ссылки, описание, примеры):")
    await state.set_state(RegisterStates.portfolio)


@dp.message(RegisterStates.portfolio)
async def reg_portfolio(message: types.Message, state: FSMContext):
    portfolio = message.text.strip()
    if len(portfolio) < MIN_PORT_LEN or len(portfolio) > MAX_PORT_LEN:
        await message.answer(f"Портфолио должно быть от {MIN_PORT_LEN} до {MAX_PORT_LEN} символов!\nСейчас: {len(portfolio)}")
        return
    if any(word in portfolio.lower() for word in SPAM_WORDS):
        await message.answer("В портфолио запрещены рекламные слова и ссылки!")
        return
    
    await state.update_data(portfolio=portfolio)
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
    user_id = message.from_user.id
    
    # Проверка роли
    user = get_user(user_id)
    if not user or user[1] != "customer":
        await message.answer("Эта функция доступна только заказчикам.")
        return
    
    # Анти-спам: не чаще 1 заказа в 10 минут
    now = datetime.now().timestamp()
    if user_id in user_last_order and now - user_last_order[user_id] < ORDER_COOLDOWN:
        left = int(ORDER_COOLDOWN - (now - user_last_order[user_id]))
        mins = left // 60
        secs = left % 60
        await message.answer(f"Слишком часто! Подождите ещё {mins} мин {secs} сек перед новым заказом.")
        return
    
    user_last_order[user_id] = now
    
    await message.answer(
        f"Создание нового заказа\n\n"
        f"• Название: 10–100 символов\n"
        f"• Описание: 50–2000 символов\n"
        f"• Максимум 5 файлов\n\n"
        f"Введите название заказа:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.set_state(OrderStates.title)

@dp.message(OrderStates.title)
async def order_title(message: types.Message, state: FSMContext):
    title = message.text.strip()
    if len(title) < MIN_TITLE_LEN or len(title) > MAX_TITLE_LEN:
        await message.answer(f"Название должно быть от {MIN_TITLE_LEN} до {MAX_TITLE_LEN} символов!")
        return
    if any(word in title.lower() for word in SPAM_WORDS):
        await message.answer("Название содержит запрещённые слова! Попробуй без рекламы.")
        return
    await state.update_data(title=title)
    await state.set_state(OrderStates.description)
    await message.answer("Опишите задачу подробно:")

@dp.message(OrderStates.description)
async def order_desc(message: types.Message, state: FSMContext):
    desc = message.text.strip()
    if len(desc) < MIN_DESC_LEN or len(desc) > MAX_DESC_LEN:
        await message.answer(f"Описание должно быть от {MIN_DESC_LEN} до {MAX_DESC_LEN} символов!")
        return
    if any(word in desc.lower() for word in SPAM_WORDS):
        await message.answer("Описание содержит запрещённые слова! Без рекламы и ссылок.")
        return
    await state.update_data(description=desc)
    # Устанавливаем следующее состояние для файлов
    await state.set_state(OrderStates.files)
    await message.answer("Пришлите файлы (если есть). После всех — нажмите кнопку ниже.", 
                         reply_markup=types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="Пропустить файлы")]], resize_keyboard=True))

@dp.message(F.text == "Пропустить файлы")
async def skip_files(message: types.Message, state: FSMContext):
    await message.answer("Укажите бюджет (в тенге, только число):", 
                         reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(OrderStates.price)


@dp.message(OrderStates.files, F.document | F.photo)
async def order_files(message: types.Message, state: FSMContext):
    data = await state.get_data()
    files = data.get("files", [])
    
    # Лимит 5 файлов
    if len(files) >= 5:
        await message.answer("⚠️ Максимум 5 файлов на заказ! Нажмите «Пропустить файлы», чтобы продолжить.")
        return
    
    # Добавляем файл
    if message.document:
        files.append(message.document.file_id)
    elif message.photo:
        files.append(message.photo[-1].file_id)  # самая чёткая фотка
    
    await state.update_data(files=files)
    await message.answer(f"✅ Файл добавлен! Всего: {len(files)} из 5\n\n"
                         "Пришлите ещё или нажмите кнопку ниже:", 
                         reply_markup=types.ReplyKeyboardMarkup(
                             keyboard=[[types.KeyboardButton(text="Пропустить файлы")]], 
                             resize_keyboard=True
                         ))
    # НЕ делаем return — остаёмся в состоянии files

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
        await message.answer(f"<b>Заказ #{oid}</b>\n{title}\n💰 {price} ₸\nСложность: {comp}", reply_markup=kb)

# === ОТКЛИК ===
@dp.callback_query(lambda c: c.data.startswith("apply_"))
async def apply_order(call: types.CallbackQuery):
    order_id = int(call.data.split("_")[1])
    worker_id = call.from_user.id

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # Проверяем, не откликался ли уже
    cur.execute("SELECT id FROM applications WHERE order_id = ? AND worker_id = ?", (order_id, worker_id))
    if cur.fetchone():
        await call.answer("Вы уже откликнулись на этот заказ!", show_alert=True)
        conn.close()
        return

    # Проверяем, не взят ли заказ уже
    cur.execute("SELECT status, customer_id FROM orders WHERE id = ?", (order_id,))
    order = cur.fetchone()
    if order[0] != "active":
        await call.answer("Заказ уже взят или закрыт", show_alert=True)
        conn.close()
        return

    # Добавляем отклик
    cur.execute("INSERT INTO applications (order_id, worker_id) VALUES (?, ?)", (order_id, worker_id))
    conn.commit()

    # Уведомляем заказчика
    customer_id = order[1]
    worker = get_user(worker_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подтвердить", callback_data=f"accept_{order_id}_{worker_id}")],
        [InlineKeyboardButton(text="Отклонить", callback_data=f"reject_{order_id}_{worker_id}")],
        [InlineKeyboardButton(text="Все отклики", callback_data=f"view_apps_{order_id}")]
    ])

    await bot.send_message(customer_id, f"""
Новый отклик на заказ <b>#{order_id}</b>!

Исполнитель: <b>{worker[2]}</b> @{worker[3]}
Навыки: {worker[4] or '-'}
Опыт: {worker[5] or '-'}
Портфолио: {worker[6] or '-'}
Контакт: {worker[7]}
    """, reply_markup=kb)

    await call.answer("Отклик отправлен! Заказчик увидит ваш профиль.")
    conn.close()

# === ПРОСМОТР ВСЕХ ОТКЛИКОВ ===
@dp.callback_query(lambda c: c.data.startswith("view_apps_"))
async def view_applications(call: types.CallbackQuery):
    order_id = int(call.data.split("_")[2])
    
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT u.name, u.username, u.skills, u.experience, u.portfolio, u.contact, a.worker_id 
        FROM applications a 
        JOIN users u ON a.worker_id = u.id 
        WHERE a.order_id = ? AND a.status = 'pending'
    """, (order_id,))
    apps = cur.fetchall()
    conn.close()

    if not apps:
        await call.answer("Нет активных откликов")
        return

    text = f"<b>Отклики на заказ #{order_id}:</b>\n\n"
    kb_buttons = []
    for name, username, skills, exp, port, contact, worker_id in apps:
        text += f"• <b>{name}</b> @{username}\nНавыки: {skills or '-'}\nОпыт: {exp or '-'}\nПортфолио: {port or '-'}\nКонтакт: {contact or '-'}\n\n"
        kb_buttons.append([
            InlineKeyboardButton(text=f"Подтвердить {name}", callback_data=f"accept_{order_id}_{worker_id}"),
            InlineKeyboardButton(text=f"Отклонить {name}", callback_data=f"reject_{order_id}_{worker_id}")
        ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    await call.message.answer(text, reply_markup=kb)
    await call.answer()

# === ПОДТВЕРЖДЕНИЕ ===
@dp.callback_query(lambda c: c.data.startswith("accept_"))
async def accept_application(call: types.CallbackQuery):
    _, order_id, worker_id = call.data.split("_")
    order_id = int(order_id)
    worker_id = int(worker_id)

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # Помечаем выбранного как accepted и закрываем заказ
    cur.execute("UPDATE applications SET status = 'accepted' WHERE order_id = ? AND worker_id = ?", (order_id, worker_id))
    cur.execute("UPDATE orders SET worker_id = ?, status = 'taken' WHERE id = ?", (worker_id, order_id))

    # Всем остальным — rejected
    cur.execute("""
        UPDATE applications 
        SET status = 'rejected' 
        WHERE order_id = ? AND worker_id != ? AND status = 'pending'
    """, (order_id, worker_id))

    conn.commit()

    # Уведомляем принятого
    worker = get_user(worker_id)
    customer = get_user(call.from_user.id)
    await bot.send_message(worker_id, f"""
Ваша заявка на заказ <b>#{order_id}</b> ПОДТВЕРЖДЕНА!

Заказчик: {customer[2]} @{customer[3]}
Контакт: {customer[7] or 'не указан'}

Пишите ему напрямую — удачной работы!
    """)

    # Уведомляем отклонённых
    cur.execute("SELECT worker_id FROM applications WHERE order_id = ? AND status = 'rejected'", (order_id,))
    for (wid,) in cur.fetchall():
        await bot.send_message(wid, f"К сожалению, на заказ #{order_id} выбран другой исполнитель. Удачи в следующих заказах!")

    conn.close()
    await call.answer("Исполнитель подтверждён! Остальные уведомлены об отклонении.")
    await call.message.edit_text(call.message.text + "\n\n✅ Исполнитель подтверждён!")

# === ОТКЛОНЕНИЕ ===
@dp.callback_query(lambda c: c.data.startswith("reject_"))
async def reject_application(call: types.CallbackQuery):
    _, order_id, worker_id = call.data.split("_")
    order_id = int(order_id)
    worker_id = int(worker_id)

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE applications SET status = 'rejected' WHERE order_id = ? AND worker_id = ?", (order_id, worker_id))
    conn.commit()
    conn.close()

    await bot.send_message(worker_id, f"Ваша заявка на заказ #{order_id} отклонена заказчиком.")
    await call.answer("Отклик отклонён")
    await call.message.edit_text(call.message.text + "\n\n❌ Отклик отклонён")

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
        SELECT o.id, o.title, a.status, u.name, u.username 
        FROM applications a
        JOIN orders o ON a.order_id = o.id
        JOIN users u ON o.customer_id = u.id 
        WHERE a.worker_id = ? AND a.status = 'pending'
    """, (user_id,))
    pending = cur.fetchall()
    
    # Взятые (accepted / taken)
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