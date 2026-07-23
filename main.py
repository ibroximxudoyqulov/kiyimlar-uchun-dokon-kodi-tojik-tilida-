import os
import math
import json
import logging
import asyncio
import aiosqlite
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove
)

# ==========================================
# 1. SOZLAMALAR VA KONFIGURATSIYA
# ==========================================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_PATH = "database.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==========================================
# 2. MA'LUMOTLAR BAZASI FUNKSIYALARI (SQLite)
# ==========================================
async def init_db():
    """Базаи маълумоти SQLite-ро ҳангоми оғози кор созмон медиҳад."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                phone_number TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                image_id TEXT,
                is_available INTEGER DEFAULT 1,
                FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                items_json TEXT NOT NULL,
                total_price REAL NOT NULL,
                payment_photo_id TEXT,
                status TEXT DEFAULT 'PENDING_PAYMENT_APPROVAL',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def add_user(user_id: int, full_name: str, phone_number: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, full_name, phone_number) VALUES (?, ?, ?)",
            (user_id, full_name, phone_number)
        )
        await db.commit()

async def get_all_user_ids() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        await db.commit()

async def get_setting(key: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def add_category(name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO categories (name) VALUES (?)", (name,))
        await db.commit()

async def get_categories() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM categories") as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def add_product(category_id: int, name: str, price: float, image_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO products (category_id, name, price, image_id) VALUES (?, ?, ?, ?)",
            (category_id, name, price, image_id)
        )
        await db.commit()

async def get_products_by_category(category_id: int, available_only: bool = True) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM products WHERE category_id = ?"
        params = [category_id]
        if available_only:
            query += " AND is_available = 1"
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def toggle_product_stock(product_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_available FROM products WHERE id = ?", (product_id,)) as cursor:
            row = await cursor.fetchone()
            new_status = 0 if row[0] == 1 else 1
        await db.execute("UPDATE products SET is_available = ? WHERE id = ?", (new_status, product_id))
        await db.commit()
        return new_status

async def get_product(product_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM products WHERE id = ?", (product_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def create_order(user_id: int, items: dict, total_price: float, payment_photo_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO orders (user_id, items_json, total_price, payment_photo_id) VALUES (?, ?, ?, ?)",
            (user_id, json.dumps(items), total_price, payment_photo_id)
        )
        await db.commit()
        return cursor.lastrowid

async def update_order_status(order_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        await db.commit()

# ==========================================
# 3. YORDAMCHI FUNKSIYALAR VA HOLATLAR (FSM)
# ==========================================
class AdminStates(StatesGroup):
    waiting_for_payment_info = State()
    waiting_for_geo_settings = State()
    waiting_for_category_name = State()
    waiting_for_product_name = State()
    waiting_for_product_price = State()
    waiting_for_product_photo = State()
    waiting_for_broadcast_msg = State()
    waiting_for_reject_reason = State()

class CustomerStates(StatesGroup):
    waiting_for_location = State()
    waiting_for_receipt = State()

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Масофаро байни ду нуқта бо км ҳисоб мекунад."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def get_customer_main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="☕️ Меню"), KeyboardButton(text="🛍 Сабад")],
            [KeyboardButton(text="📍 Маълумоти расонидан"), KeyboardButton(text="📞 Тамос бо мо")]
        ],
        resize_keyboard=True
    )

def get_admin_panel_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Маълумоти пардохт", callback_data="admin_payment"), InlineKeyboardButton(text="⚙️ Макон ва расонидан", callback_data="admin_geo")],
            [InlineKeyboardButton(text="📁 Идораи категорияҳо", callback_data="admin_cats"), InlineKeyboardButton(text="🍕 Иловаи маҳсулот", callback_data="admin_add_prod")],
            [InlineKeyboardButton(text="📦 Ҳолати анбор (Стоп-лист)", callback_data="admin_stock"), InlineKeyboardButton(text="📢 Паёми умумӣ", callback_data="admin_broadcast")]
        ]
    )

# ==========================================
# 4. MIJOZLAR UCHUN BOT MANTIQI
# ==========================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await add_user(message.from_user.id, message.from_user.full_name)
    await message.answer(
        f"👋 Хуш омадед, {message.from_user.first_name}!\nМенюи моро аз назар гузаронед ва фармоиши худро бевосита тавассути Telegram ба расмият дароред.",
        reply_markup=get_customer_main_kb()
    )

@dp.message(F.text == "📍 Маълумоти расонидан")
async def delivery_info(message: types.Message):
    city = await get_setting("allowed_city") or "Муайян нашудааст"
    radius = await get_setting("delivery_radius_km") or "Муайян нашудааст"
    info = (
        f"<b>📍 Маълумот оид ба расонидан</b>\n\n"
        f"• Шаҳри фаъолият: {city}\n"
        f"• Масофаи расонидан: то {radius} км\n"
        f"• Соатҳои корӣ: 09:00 - 23:00\n"
    )
    await message.answer(info, parse_mode="HTML")

@dp.message(F.text == "📞 Тамос бо мо")
async def contact_admin(message: types.Message):
    payment_info = await get_setting("payment_info") or "Маълумоти тамос вуҷуд надорад."
    await message.answer(f"📞 <b>Тамос ва маълумоти пардохт:</b>\n\n{payment_info}", parse_mode="HTML")

@dp.message(F.text == "☕️ Меню")
async def show_categories(message: types.Message):
    categories = await get_categories()
    if not categories:
        await message.answer("Айни замон меню холӣ аст. Лутфан баъдтар санҷед!")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=cat['name'], callback_data=f"cat_{cat['id']}")] for cat in categories
        ]
    )
    await message.answer("Лутфан категорияро интихоб кунед:", reply_markup=kb)

@dp.callback_query(F.data.startswith("cat_"))
async def show_products(callback: types.CallbackQuery):
    cat_id = int(callback.data.split("_")[1])
    products = await get_products_by_category(cat_id, available_only=True)
    await callback.answer()

    if not products:
        await callback.message.edit_text("Дар ин категория маҳсулот вуҷуд надорад.", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Қафо", callback_data="back_to_cats")]]
        ))
        return

    for prod in products:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="➕ Ба сабад илова кардан", callback_data=f"add_cart_{prod['id']}")]]
        )
        caption = f"<b>{prod['name']}</b>\nНарх: {prod['price']:.2f} сомонӣ"
        if prod['image_id']:
            await callback.message.answer_photo(photo=prod['image_id'], caption=caption, parse_mode="HTML", reply_markup=kb)
        else:
            await callback.message.answer(caption, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "back_to_cats")
async def back_to_categories(callback: types.CallbackQuery):
    categories = await get_categories()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c['name'], callback_data=f"cat_{c['id']}")] for c in categories])
    await callback.message.edit_text("Лутфан категорияро интихоб кунед:", reply_markup=kb)

@dp.callback_query(F.data.startswith("add_cart_"))
async def add_to_cart(callback: types.CallbackQuery, state: FSMContext):
    prod_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    cart = data.get("cart", {})
    
    cart[str(prod_id)] = cart.get(str(prod_id), 0) + 1
    await state.update_data(cart=cart)
    await callback.answer("Ба сабад илова шуд! 🛒", show_alert=False)

@dp.message(F.text == "🛍 Сабад")
async def view_cart(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cart: dict = data.get("cart", {})

    if not cart:
        await message.answer("Сабади шумо холӣ аст.")
        return

    summary = "<b>🛍 Сабади шумо:</b>\n\n"
    total_price = 0.0

    for p_id, qty in cart.items():
        product = await get_product(int(p_id))
        if product:
            item_total = product['price'] * qty
            total_price += item_total
            summary += f"• {product['name']} x{qty} = {item_total:.2f} сомонӣ\n"

    summary += f"\n<b>Маблағи умумӣ: {total_price:.2f} сомонӣ</b>"
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Фармоиш додан", callback_data="checkout")],
            [InlineKeyboardButton(text="🗑 Тоза кардани сабад", callback_data="clear_cart")]
        ]
    )
    await message.answer(summary, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "clear_cart")
async def clear_cart(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(cart={})
    await callback.message.edit_text("Сабади шумо тоза карда шуд.")

@dp.callback_query(F.data == "checkout")
async def start_checkout(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(CustomerStates.waiting_for_location)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Фиристодани макони ҷойгиршавӣ (Location)", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await callback.message.answer("Барои санҷиши имконияти расонидан, лутфан макони худро фиристед:", reply_markup=kb)

@dp.message(CustomerStates.waiting_for_location, F.location)
async def process_location(message: types.Message, state: FSMContext):
    u_lat = message.location.latitude
    u_lon = message.location.longitude

    cafe_lat = await get_setting("location_lat")
    cafe_lon = await get_setting("location_lon")
    max_radius = await get_setting("delivery_radius_km")
    allowed_city = await get_setting("allowed_city") or "минтақаи фаъолияти мо"

    if cafe_lat and cafe_lon and max_radius:
        dist = haversine(u_lat, u_lon, float(cafe_lat), float(cafe_lon))
        if dist > float(max_radius):
            await message.answer(
                f"❌ Бубахшед, макони шумо дар масофаи {dist:.1f} км қарор дорад. Мо танҳо дар ҳудуди {max_radius} км дар шаҳри {allowed_city} расонида метавонем.",
                reply_markup=get_customer_main_kb()
            )
            await state.clear()
            return

    await state.set_state(CustomerStates.waiting_for_receipt)
    payment_info = await get_setting("payment_info") or "Барои пардохт бо маъмурият дар тамос шавед."
    
    data = await state.get_data()
    cart = data.get("cart", {})
    total = sum([(await get_product(int(p)))['price'] * q for p, q in cart.items()])
    await state.update_data(order_total=total)

    msg = (
        f"<b>📍 Макон тасдиқ шуд!</b>\n\n"
        f"<b>Маблағи пардохт: {total:.2f} сомонӣ</b>\n\n"
        f"<b>Дастурамали пардохт:</b>\n{payment_info}\n\n"
        "📸 Барои ба анҷом расонидани фармоиш, лутфан <b>расм ё скриншоти расиди пардохтро (чек)</b> фиристед."
    )
    await message.answer(msg, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())

@dp.message(CustomerStates.waiting_for_receipt, F.photo)
async def process_receipt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cart = data.get("cart", {})
    total = data.get("order_total", 0.0)
    photo_id = message.photo[-1].file_id

    order_id = await create_order(
        user_id=message.from_user.id,
        items=cart,
        total_price=total,
        payment_photo_id=photo_id
    )

    await state.clear()
    await message.answer("✅ Фармоиш қабул шуд! Пардохти шумо дар ҳолати интизории тасдиқи маъмурият қарор дорад.", reply_markup=get_customer_main_kb())

    items_desc = "\n".join([f"• {(await get_product(int(p)))['name']} x{q}" for p, q in cart.items()])
    admin_card = (
        f"🚨 <b>ФАРМОИШИ НАВ #{order_id}</b>\n\n"
        f"<b>Муштарӣ:</b> {message.from_user.full_name} (@{message.from_user.username})\n"
        f"<b>ID:</b> <code>{message.from_user.id}</code>\n\n"
        f"<b>Маҳсулот:</b>\n{items_desc}\n\n"
        f"<b>Маблағи умумӣ:</b> {total:.2f} сомонӣ"
    )
    
    approve_kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Тасдиқ", callback_data=f"ord_app_{order_id}"),
            InlineKeyboardButton(text="❌ Рад кардан", callback_data=f"ord_rej_{order_id}")
        ]]
    )
    await bot.send_photo(chat_id=ADMIN_ID, photo=photo_id, caption=admin_card, parse_mode="HTML", reply_markup=approve_kb)

# ==========================================
# 5. ADMIN PANEL MANTIQI
# ==========================================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if not is_admin(message.from_user.id): return
    await message.answer("⚙️ <b>Панели идораи маъмурият</b>", parse_mode="HTML", reply_markup=get_admin_panel_kb())

@dp.callback_query(F.data.startswith("ord_app_"))
async def approve_order(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    order_id = int(callback.data.split("_")[2])
    
    await update_order_status(order_id, "APPROVED")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n<b>Ҳолат: ✅ ТАСДИҚ ШУД</b>", parse_mode="HTML")
    
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,)) as cur:
            row = await cur.fetchone()
            if row:
                try:
                    await bot.send_message(chat_id=row[0], text=f"🎉 Пардохти шумо барои фармоиши #{order_id} тасдиқ шуд! Ғизои шумо омода шуда истодааст.")
                except Exception as e:
                    logging.error(f"Хатогӣ ҳангоми ирсоли паём: {e}")

@dp.callback_query(F.data.startswith("ord_rej_"))
async def start_reject_order(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    order_id = int(callback.data.split("_")[2])
    await state.update_data(reject_order_id=order_id)
    await state.set_state(AdminStates.waiting_for_reject_reason)
    await callback.message.answer(f"Лутфан сабаби рад кардани фармоиши #{order_id}-ро нависед:")

@dp.message(AdminStates.waiting_for_reject_reason)
async def process_reject_reason(message: types.Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("reject_order_id")
    reason = message.text

    await update_order_status(order_id, "REJECTED")
    await state.clear()
    await message.answer(f"Фармоиши #{order_id} рад карда шуд.")

    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,)) as cur:
            row = await cur.fetchone()
            if row:
                try:
                    await bot.send_message(chat_id=row[0], text=f"❌ Фармоиши шумо #{order_id} рад карда шуд.\nСабаб: {reason}")
                except Exception as e:
                    logging.error(f"Хатогӣ ҳангоми ирсоли паём: {e}")

@dp.callback_query(F.data == "admin_payment")
async def edit_payment_info(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(AdminStates.waiting_for_payment_info)
    await callback.message.answer("Маълумоти бонкиро ворид кунед (масалан: Номи бонк, Рақами корт/телефон, Ному насаб):")

@dp.message(AdminStates.waiting_for_payment_info)
async def save_payment_info(message: types.Message, state: FSMContext):
    await set_setting("payment_info", message.text)
    await state.clear()
    await message.answer("✅ Маълумоти пардохт нав карда шуд.")

@dp.callback_query(F.data == "admin_geo")
async def edit_geo_settings(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(AdminStates.waiting_for_geo_settings)
    msg = "Номи шаҳр, арз, тӯл ва радиуси расониданро ба ин шакл фиристед:\n<code>НомиШаҳр, Арз, Тӯл, Радиус</code>\n\nМисол: <code>Душанбе, 38.5598, 68.7870, 15.5</code>"
    await callback.message.answer(msg, parse_mode="HTML")

@dp.message(AdminStates.waiting_for_geo_settings)
async def save_geo_settings(message: types.Message, state: FSMContext):
    try:
        parts = [p.strip() for p in message.text.split(",")]
        await set_setting("allowed_city", parts[0])
        await set_setting("location_lat", parts[1])
        await set_setting("location_lon", parts[2])
        await set_setting("delivery_radius_km", parts[3])
        await state.clear()
        await message.answer("✅ Танзимоти макон ва расонидан сабт шуд!")
    except Exception:
        await message.answer("❌ Формат нодуруст аст. Лутфан бо формати Шаҳр, Арз, Тӯл, Радиус такрор кунед.")

@dp.callback_query(F.data == "admin_add_prod")
async def admin_add_product_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    categories = await get_categories()
    if not categories:
        await callback.message.answer("Аввал ягон категория илова кунед!")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c['name'], callback_data=f"sel_cat_{c['id']}")] for c in categories])
    await callback.message.answer("Категорияро барои маҳсулоти нав интихоб кунед:", reply_markup=kb)

@dp.callback_query(F.data.startswith("sel_cat_"))
async def admin_select_category_for_prod(callback: types.CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split("_")[2])
    await state.update_data(target_cat_id=cat_id)
    await state.set_state(AdminStates.waiting_for_product_name)
    await callback.message.answer("Номи маҳсулотро ворид кунед:")

@dp.message(AdminStates.waiting_for_product_name)
async def admin_prod_name(message: types.Message, state: FSMContext):
    await state.update_data(prod_name=message.text)
    await state.set_state(AdminStates.waiting_for_product_price)
    await message.answer("Нархи маҳсулотро нависед (масалан: 25.50):")

@dp.message(AdminStates.waiting_for_product_price)
async def admin_prod_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text)
        await state.update_data(prod_price=price)
        await state.set_state(AdminStates.waiting_for_product_photo)
        await message.answer("Расми маҳсулотро фиристед:")
    except ValueError:
        await message.answer("❌ Нарх нодуруст аст. Танҳо рақам ворид кунед:")

@dp.message(AdminStates.waiting_for_product_photo, F.photo)
async def admin_prod_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id
    await add_product(data['target_cat_id'], data['prod_name'], data['prod_price'], photo_id)
    await state.clear()
    await message.answer(f"✅ Маҳсулоти '{data['prod_name']}' бо муваффақият илова шуд!")

@dp.callback_query(F.data == "admin_cats")
async def manage_categories(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(AdminStates.waiting_for_category_name)
    await callback.message.answer("Номи категорияи навро ворид кунед:")

@dp.message(AdminStates.waiting_for_category_name)
async def save_category(message: types.Message, state: FSMContext):
    await add_category(message.text)
    await state.clear()
    await message.answer(f"✅ Категорияи '{message.text}' сохта шуд.")

@dp.callback_query(F.data == "admin_stock")
async def toggle_stock_list(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id): return
    categories = await get_categories()
    
    kb_list = []
    for cat in categories:
        products = await get_products_by_category(cat['id'], available_only=False)
        for p in products:
            status_icon = "🟢" if p['is_available'] == 1 else "🔴"
            kb_list.append([InlineKeyboardButton(text=f"{status_icon} {p['name']}", callback_data=f"tog_stock_{p['id']}")])
    
    await callback.message.answer("Барои тағйир додани ҳолати маҳсулот ба рӯи он пахш кунед (🟢 Дар анбор ҳаст / 🔴 Стоп-лист):", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("tog_stock_"))
async def process_stock_toggle(callback: types.CallbackQuery):
    p_id = int(callback.data.split("_")[2])
    new_status = await toggle_product_stock(p_id)
    status_str = "Дар анбор 🟢" if new_status == 1 else "Стоп-лист 🔴"
    await callback.answer(f"Ҳолати маҳсулот иваз шуд: {status_str}")

@dp.callback_query(F.data == "admin_broadcast")
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await state.set_state(AdminStates.waiting_for_broadcast_msg)
    await callback.message.answer("Матни паёмро барои фиристодан ба ҳамаи муштариён ворид кунед:")

@dp.message(AdminStates.waiting_for_broadcast_msg)
async def process_broadcast(message: types.Message, state: FSMContext):
    users = await get_all_user_ids()
    await state.clear()
    
    count = 0
    for uid in users:
        try:
            await bot.send_message(chat_id=uid, text=message.text)
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            continue
            
    await message.answer(f"📢 Паёми умумӣ анҷом ёфт. Ба {count} аз {len(users)} муштарӣ фиристода шуд.")

# ==========================================
# 6. DASTURNI ISHGA TUSHIRISH
# ==========================================
async def main():
    await init_db()
    logging.info("Базаи маълумот бо муваффақият пайваст шуд.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
