import asyncio
import logging
import random
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
)

# --- SOZLAMALAR ---
BOT_TOKEN = "BOT_TOKENINGIZNI_SHU_YERGA_YOZING"
ADMIN_ID = 123456789  # Bosh Admin Telegram ID'si

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- MA'LUMOTLAR BAZASI (SQLITE) ---
def init_db():
    conn = sqlite3.connect("clothing_store.db")
    cursor = conn.cursor()
    
    # Kiyim kategoriyalari (Admin o'zi qo'shadi)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name_tj TEXT
    )""")
    
    # Kiyimlar va ularning razmerlari jadvali
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER,
        name TEXT,
        price REAL,
        unit TEXT,
        photo_id TEXT,
        start_size TEXT,
        end_size TEXT,
        weight_info TEXT
    )""")
    
    # Kuryerlar va holati (FREE / BUSY)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS couriers (
        user_id INTEGER PRIMARY KEY,
        status TEXT DEFAULT 'FREE'
    )""")
    
    cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    
    # Buyurtmalar jadvali
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        phone TEXT,
        items TEXT,
        total_price REAL,
        delivery_fee REAL,
        status TEXT,
        code TEXT,
        courier_id INTEGER,
        receipt_photo TEXT,
        created_at TEXT
    )""")
    
    # Baza bo'sh bo'lsa, namunaviy kategoriyalar qo'shish
    cursor.execute("SELECT COUNT(*) FROM categories")
    if cursor.fetchone()[0] == 0:
        default_cats = [
            ("👕 Либосҳои мардона",),
            ("👗 Либосҳои занона",),
            ("👶 Либосҳои кӯдакона",),
            ("👟 Пойафзол (Аёққий)",)
        ]
        cursor.executemany("INSERT INTO categories (name_tj) VALUES (?)", default_cats)
        
    conn.commit()
    conn.close()

init_db()

def get_db():
    return sqlite3.connect("clothing_store.db")

def set_setting(key, val):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(val)))
    conn.commit()
    conn.close()

def get_setting(key):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    res = cur.fetchone()
    conn.close()
    return res[0] if res else None

# --- FSM STATES ---
class AdminState(StatesGroup):
    ADD_CATEGORY = State()
    ADD_PROD_NAME = State()
    ADD_PROD_PRICE = State()
    ADD_PROD_UNIT = State()
    ADD_START_SIZE = State()
    ADD_END_SIZE = State()
    ADD_WEIGHT_INFO = State()
    ADD_PROD_PHOTO = State()
    SET_DELIVERY_FEE = State()
    ADD_COURIER = State()

class CustomerState(StatesGroup):
    SELECT_SIZE = State()
    WAITING_PHONE = State()
    WAITING_LOCATION = State()
    WAITING_RECEIPT = State()

class CourierState(StatesGroup):
    ENTER_CODE = State()

# --- BUTTONS ---
def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Ба ақиб", callback_data="cancel_action")]
    ])

def skip_or_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Идома додан (Гузаштан)", callback_data="skip_step")],
        [InlineKeyboardButton(text="⬅️ Ба ақиб", callback_data="cancel_action")]
    ])

def main_customer_kb(user_id):
    buttons = [
        [KeyboardButton(text="🛍 Каталоги либосҳо"), KeyboardButton(text="🛒 Сабад")],
        [KeyboardButton(text="📦 Фармоишҳои ман"), KeyboardButton(text="📍 Ҷойгиршавии мағоза")]
    ]
    if user_id == ADMIN_ID:
        buttons.append([KeyboardButton(text="⚙️ Панели админ")])
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM couriers WHERE user_id=?", (user_id,))
    if cur.fetchone():
        buttons.append([KeyboardButton(text="🚴‍♂️ Панели курьер")])
    conn.close()

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Ассалому алайкум! Ба мағозаи либосҳои мо хуш омадед.\n"
        "Лутфан, аз менюи поён бахшро интихоб кунед:",
        reply_markup=main_customer_kb(message.from_user.id)
    )

@dp.callback_query(F.data == "cancel_action")
async def cancel_action(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Амал бекор карда шуд.", reply_markup=main_customer_kb(callback.from_user.id))

# --- DO'KON JOYLASHUVI ---
@dp.message(F.text == "📍 Ҷойгиршавии мағоза")
async def show_store_loc(message: types.Message):
    loc_data = get_setting("store_loc")
    if loc_data:
        lat, lon = map(float, loc_data.split(","))
        await message.answer_location(latitude=lat, longitude=lon)
    else:
        await message.answer("📍 Ҷойгиршавии мағоза ҳануз танзим نشدهаст.")

# --- MIJOZ BUYURTMALAR HOLATI ---
@dp.message(F.text == "📦 Фармоишҳои ман")
async def my_orders(message: types.Message):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, total_price, status, created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 5", (message.from_user.id,))
    orders = cur.fetchall()
    conn.close()

    if not orders:
        await message.answer("📦 Шумо ҳануз ҳеҷ фармоиш надоред.")
        return

    text = "📦 **Фармоишҳои охирини шумо:**\n\n"
    status_map = {
        "PENDING": "⏳ Интизории тасдиқи админ",
        "WAITING_COURIER": "⌛️ Интизории курьери озод",
        "ACCEPTED": "🛵 Курьер дар роҳ аст",
        "COMPLETED": "✅ Муваффақона расонида шуд",
        "REJECTED": "❌ Рад карда шуд"
    }

    for o in orders:
        st = status_map.get(o[2], o[2])
        text += f"🔹 Фармоиши №{o[0]}\n💰 Сумма: {o[1]:,} сомонӣ\n📊 Ҳолат: {st}\n📅 Вақт: {o[3][:16]}\n--------------------\n"

    await message.answer(text)

# --- KIYIM KATEGORIYALARI VA MAHSULOTLAR ---
@dp.message(F.text == "🛍 Каталоги либосҳо")
async def show_categories(message: types.Message):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name_tj FROM categories")
    cats = cur.fetchall()
    conn.close()

    if not cats:
        await message.answer("🛍 Ҳануз ҳеҷ категория илова نشدهаст.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=c[1], callback_data=f"user_cat_{c[0]}")] for c in cats
    ])
    await message.answer("📂 Категорияи либосҳоро интихоб кунед:", reply_markup=kb)

@dp.callback_query(F.data.startswith("user_cat_"))
async def show_products_list(callback: types.CallbackQuery):
    cat_id = int(callback.data.split("_")[2])
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, price, unit, photo_id, start_size, end_size, weight_info FROM products WHERE category_id=?", (cat_id,))
    prods = cur.fetchall()
    conn.close()

    if not prods:
        await callback.answer("❌ Дар ин категория либос ёфт нашуд.", show_alert=True)
        return

    await callback.message.delete()
    for p in prods:
        caption = (
            f"👕 **{p[1]}**\n"
            f"💰 Narx: {p[2]:,} сомонӣ / {p[3]}\n"
            f"📏 Андозаҳо: аз **{p[5]}** то **{p[6]}**\n"
        )
        if p[7]:
            caption += f"⚖️ Вазни тавсияви: {p[7]}\n"

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Илова ба сабад", callback_data=f"addcart_{p[0]}")],
            [InlineKeyboardButton(text="⬅️ Ба ақиб", callback_data="cancel_action")]
        ])
        await callback.message.answer_photo(photo=p[4], caption=caption, reply_markup=kb)

# --- SAVATGA QO'SHISH VA RAZMER SO'RASH ---
@dp.callback_query(F.data.startswith("addcart_"))
async def add_to_cart_handler(callback: types.CallbackQuery, state: FSMContext):
    p_id = int(callback.data.split("_")[1])
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT start_size, end_size FROM products WHERE id=?", (p_id,))
    p = cur.fetchone()
    conn.close()

    await state.update_data(selected_prod_id=p_id)
    await callback.message.answer(f"📏 Андозаро ворид кунед (Аз **{p[0]}** то **{p[1]}**):", reply_markup=back_kb())
    await state.set_state(CustomerState.SELECT_SIZE)

@dp.message(CustomerState.SELECT_SIZE)
async def process_customer_size(message: types.Message, state: FSMContext):
    data = await state.get_data()
    p_id = data.get("selected_prod_id")
    input_size = message.text.strip()

    await save_to_cart(p_id, size=input_size, state=state)
    await message.answer(f"✅ Андозаи {input_size} ба сабад илова шуд!", reply_markup=main_customer_kb(message.from_user.id))
    await state.clear()

async def save_to_cart(p_id, size, state: FSMContext):
    data = await state.get_data()
    cart = data.get("cart", {})
    key = f"{p_id}_{size}" if size else str(p_id)
    cart[key] = cart.get(key, 0) + 1
    await state.update_data(cart=cart)

# --- SAVAT VA BUYURTMA BERISH ---
@dp.message(F.text == "🛒 Сабад")
async def show_cart(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cart = data.get("cart", {})
    if not cart:
        await message.answer("🛒 Сабади шумо холагӣ аст.")
        return

    delivery_fee = float(get_setting("delivery_fee") or 10.0)
    conn = get_db()
    cur = conn.cursor()
    text = "🛒 **Либосҳои интихобкардаи шумо:**\n\n"
    total_prod = 0

    for key, count in cart.items():
        p_id = int(key.split("_")[0])
        size_info = f" (Андоза: {key.split('_')[1]})" if "_" in key else ""
        cur.execute("SELECT name, price, unit FROM products WHERE id=?", (p_id,))
        p = cur.fetchone()
        if p:
            cost = p[1] * count
            total_prod += cost
            text += f"▪️ {p[0]}{size_info} x {count} = {cost:,} сомонӣ\n"

    conn.close()
    grand_total = total_prod + delivery_fee
    text += f"\n👕 Либосҳо: {total_prod:,} сомонӣ\n🛵 Расонидан (Доставка): {delivery_fee:,} сомонӣ\n💵 **Ҷамъи кулл:** {grand_total:,} сомонӣ"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Танзими фармоиш", callback_data="start_checkout")],
        [InlineKeyboardButton(text="🗑 Тоза кардани сабад", callback_data="clear_cart")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "clear_cart")
async def clear_cart(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(cart={})
    await callback.message.answer("🗑 Сабад тоза карда шуд!")

@dp.callback_query(F.data == "start_checkout")
async def start_checkout(callback: types.CallbackQuery, state: FSMContext):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Фиристодани рақам", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await callback.message.answer("Лутфан, рақами телефони худро фиристед:", reply_markup=kb)
    await state.set_state(CustomerState.WAITING_PHONE)

@dp.message(CustomerState.WAITING_PHONE, F.contact)
async def process_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Фиристодани ҷойгиршавӣ (Локатсия)", request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer("Акнун локатсияи худро фиристед:", reply_markup=kb)
    await state.set_state(CustomerState.WAITING_LOCATION)

@dp.message(CustomerState.WAITING_LOCATION, F.location)
async def process_location(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    
    card_name = get_setting("card_name") or "Алиф / Эсхата"
    card_phone = get_setting("card_phone") or "+992000000000"
    
    await message.answer(
        f"💳 **Тӯловро иҷро кунед:**\n"
        f"Карта: **{card_name}**\n"
        f"Рақам: **{card_phone}**\n\n"
        f"⚠️ **МУҲИМ:** Тӯловро иҷро карда, **акси чекро (скриншот)** ба ҳамин ҷо фиристед:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(CustomerState.WAITING_RECEIPT)

@dp.message(CustomerState.WAITING_RECEIPT, F.photo)
async def process_receipt(message: types.Message, state: FSMContext):
    receipt_photo_id = message.photo[-1].file_id
    data = await state.get_data()
    cart = data.get("cart", {})
    delivery_fee = float(get_setting("delivery_fee") or 10.0)

    conn = get_db()
    cur = conn.cursor()
    
    total_prod = 0
    items_text = ""
    for key, count in cart.items():
        p_id = int(key.split("_")[0])
        size_str = f" (Андоза: {key.split('_')[1]})" if "_" in key else ""
        cur.execute("SELECT name, price FROM products WHERE id=?", (p_id,))
        p = cur.fetchone()
        if p:
            cost = p[1] * count
            total_prod += cost
            items_text += f"- {p[0]}{size_str} x {count} = {cost:,} сомонӣ\n"

    grand_total = total_prod + delivery_fee
    code = str(random.randint(10000, 99999))

    cur.execute(
        "INSERT INTO orders (user_id, phone, items, total_price, delivery_fee, status, code, receipt_photo, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (message.from_user.id, data.get("phone"), items_text, grand_total, delivery_fee, "PENDING", code, receipt_photo_id, str(datetime.now()))
    )
    order_id = cur.lastrowid
    conn.commit()
    conn.close()

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Қабул ва фиристодани курьер", callback_data=f"adm_accept_{order_id}")],
        [InlineKeyboardButton(text="❌ Рад кардани фармоиш", callback_data=f"adm_reject_{order_id}")]
    ])

    admin_msg = (
        f"🔔 **ФАРМОИШИ НАВ №{order_id}**\n"
        f"📱 Тел: +{data.get('phone')}\n"
        f"🛍 Либосҳо:\n{items_text}"
        f"🛵 Доставка: {delivery_fee} сомонӣ\n"
        f"💵 **Ҷамъ:** {grand_total:,} сомонӣ\n"
        f"🔑 Коди курьер: `{code}`\n\n"
        f"🧾 **Чеки тӯлов дар расми боло аст!**"
    )

    await bot.send_photo(ADMIN_ID, photo=receipt_photo_id, caption=admin_msg, reply_markup=admin_kb)
    await message.answer("⏳ Чек ва фармоиши шумо ба админ фиристода шуд. Лутфан сабр кунед!", reply_markup=main_customer_kb(message.from_user.id))
    await state.clear()

# --- ADMIN ACCEPT ORDER & SMART COURIER QUEUE DISPATCH ---
@dp.callback_query(F.data.startswith("adm_accept_"))
async def admin_accept_order(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    
    conn = get_db()
    cur = conn.cursor()
    
    # Bo'sh kuryerni izlash (FREE)
    cur.execute("SELECT user_id FROM couriers WHERE status='FREE' LIMIT 1")
    free_courier = cur.fetchone()

    if free_courier:
        courier_id = free_courier[0]
        cur.execute("UPDATE couriers SET status='BUSY' WHERE user_id=?", (courier_id,))
        cur.execute("UPDATE orders SET status='ACCEPTED', courier_id=? WHERE id=?", (courier_id, order_id))
        conn.commit()

        cur.execute("SELECT phone, items, total_price, user_id FROM orders WHERE id=?", (order_id,))
        o = cur.fetchone()

        cour_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Вазифа иҷро шуд (Код)", callback_data=f"cour_done_{order_id}")]
        ])
        await bot.send_message(
            courier_id,
            f"🛵 **ВАЗИФАИ НАВ №{order_id}**\n📱 Тел: +{o[0]}\n🛍 Либосҳо:\n{o[1]}💵 Ҷамъ: {o[2]:,} сомонӣ",
            reply_markup=cour_kb
        )
        await bot.send_message(o[3], f"✅ Фармоиши №{order_id} тасдиқ шуд! Курьер ба роҳ баромад.")
        await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ **ТАСДИҚ ШУД (Курьер фиристода шуд)**")
    
    else:
        cur.execute("UPDATE orders SET status='WAITING_COURIER' WHERE id=?", (order_id,))
        conn.commit()
        
        cur.execute("SELECT user_id FROM orders WHERE id=?", (order_id,))
        u_id = cur.fetchone()[0]
        
        await bot.send_message(u_id, f"✅ Фармоиши №{order_id} тасдиқ шуд. Ҳама курьерҳо банд мебошанд, ба зудӣ озод шуда расонанд.")
        await callback.message.edit_caption(caption=callback.message.caption + "\n\n⌛️ **ТАСДИҚ ШУД (Ҳама курьерҳо банд, дар навбат аст)**")

    conn.close()

@dp.callback_query(F.data.startswith("adm_reject_"))
async def admin_reject_order(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status='REJECTED' WHERE id=?", (order_id,))
    cur.execute("SELECT user_id FROM orders WHERE id=?", (order_id,))
    u_id = cur.fetchone()[0]
    conn.commit()
    conn.close()

    await bot.send_message(u_id, f"❌ Фармоиши №{order_id} рад карда шуд. Сабаб: Чек ё тӯлов тасдиқ нашуд.")
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ **РАД КАРДА ШУД**")

# --- KURYER PANELI VA AUTOMATIC QUEUE DISPATCH ---
@dp.message(F.text == "🚴‍♂️ Панели курьер")
async def courier_panel(message: types.Message):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, phone, items, total_price FROM orders WHERE courier_id=? AND status='ACCEPTED'", (message.from_user.id,))
    orders = cur.fetchall()
    conn.close()

    if not orders:
        await message.answer("🚴‍♂️ Шумо ҳозир ҳеҷ фармоиши фаъол надоред.")
        return

    for o in orders:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Вазифа иҷро шуд (Код)", callback_data=f"cour_done_{o[0]}")]
        ])
        await message.answer(f"📦 **Фармоиши №{o[0]}**\n📱 Тел: +{o[1]}\n🛍 Либосҳо:\n{o[2]}💰 Ҷамъ: {o[3]:,} сомонӣ", reply_markup=kb)

@dp.callback_query(F.data.startswith("cour_done_"))
async def cour_ask_code(callback: types.CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[2])
    await state.update_data(active_order_id=order_id)
    await callback.message.answer("🔑 Коди 5-рақамаи мизоҷро ворид кунед:", reply_markup=back_kb())
    await state.set_state(CourierState.ENTER_CODE)

@dp.message(CourierState.ENTER_CODE)
async def check_courier_code(message: types.Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("active_order_id")
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT code, user_id FROM orders WHERE id=?", (order_id,))
    res = cur.fetchone()
    
    if res and res[0] == message.text.strip():
        cur.execute("UPDATE orders SET status='COMPLETED' WHERE id=?", (order_id,))
        cur.execute("UPDATE couriers SET status='FREE' WHERE user_id=?", (message.from_user.id,))
        conn.commit()

        await message.answer("✅ Расонидан тасдиқ шуд! Ташаккур.")
        await bot.send_message(res[1], f"🎉 Фармоиши №{order_id} бо муваффақият расонида шуд! Аз харидтонатон мамнун шудем.")

        # NAVBATDA TURGAN BUYURTMANI TESHIRISH
        cur.execute("SELECT id FROM orders WHERE status='WAITING_COURIER' ORDER BY id ASC LIMIT 1")
        waiting_order = cur.fetchone()

        if waiting_order:
            w_id = waiting_order[0]
            cur.execute("UPDATE couriers SET status='BUSY' WHERE user_id=?", (message.from_user.id,))
            cur.execute("UPDATE orders SET status='ACCEPTED', courier_id=? WHERE id=?", (message.from_user.id, w_id))
            conn.commit()

            cur.execute("SELECT phone, items, total_price, user_id FROM orders WHERE id=?", (w_id,))
            wo = cur.fetchone()

            cour_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Вазифа иҷро шуд (Код)", callback_data=f"cour_done_{w_id}")]
            ])
            await message.answer(
                f"🔔 **ВАЗИФАИ НАВ АЗ НАВБАТ №{w_id}**\n📱 Тел: +{wo[0]}\n🛍 Либосҳо:\n{wo[1]}💵 Ҷамъ: {wo[2]:,} сомонӣ",
                reply_markup=cour_kb
            )
            await bot.send_message(wo[3], f"🛵 Курьер озод шуд ва ба сӯи шумо ба роҳ баромад!")

        await state.clear()
    else:
        await message.answer("❌ Коди нодуруст! Дбора ҳаракат кунед.", reply_markup=back_kb())
    conn.close()

# --- ADMIN PANEL: KIYIM KATEGORIYALARI VA MAHSULOTLARNI IDORA QILISH ---
@dp.message(F.text == "⚙️ Панели админ")
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 Идоракунии категорияҳо", callback_data="adm_cats")],
        [InlineKeyboardButton(text="🛵 Нархи доставкаро танзим кардан", callback_data="adm_delivery")],
        [InlineKeyboardButton(text="🚴‍♂️ Илова кардани курьер", callback_data="adm_add_courier")]
    ])
    await message.answer("⚙️ **Панели идоракунии Мағозаи Либос:**", reply_markup=kb)

@dp.callback_query(F.data == "adm_delivery")
async def adm_delivery_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Нархи доставкаро ворид кунед (бо сомонӣ, масалан: `10`):", reply_markup=back_kb())
    await state.set_state(AdminState.SET_DELIVERY_FEE)

@dp.message(AdminState.SET_DELIVERY_FEE)
async def adm_delivery_save(message: types.Message, state: FSMContext):
    set_setting("delivery_fee", message.text.strip())
    await message.answer("✅ Нархи доставка сабт шуд!", reply_markup=main_customer_kb(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data == "adm_add_courier")
async def adm_add_courier_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("ID-и телеграмии курьерро нависед:", reply_markup=back_kb())
    await state.set_state(AdminState.ADD_COURIER)

@dp.message(AdminState.ADD_COURIER)
async def adm_add_courier_save(message: types.Message, state: FSMContext):
    c_id = int(message.text.strip())
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO couriers (user_id, status) VALUES (?, 'FREE')", (c_id,))
    conn.commit()
    conn.close()
    await message.answer("✅ Курьер илова шуд!", reply_markup=main_customer_kb(message.from_user.id))
    await state.clear()

# --- KATEGORIYA QO'SHISH VA O'CHIRISH ---
@dp.callback_query(F.data == "adm_cats")
async def adm_cats(callback: types.CallbackQuery):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name_tj FROM categories")
    cats = cur.fetchall()
    conn.close()

    buttons = []
    for c in cats:
        buttons.append([
            InlineKeyboardButton(text=f"📂 {c[1]}", callback_data=f"adm_cat_prods_{c[0]}"),
            InlineKeyboardButton(text="🗑 Нест кардан", callback_data=f"del_cat_{c[0]}")
        ])
    
    buttons.append([InlineKeyboardButton(text="➕ Иловаи категорияи нав", callback_data="start_add_cat")])
    buttons.append([InlineKeyboardButton(text="⬅️ Ба ақиб", callback_data="cancel_action")])

    await callback.message.edit_text("Категорияҳоро интихоб кунед ё навашро илова кунед:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data == "start_add_cat")
async def start_add_cat(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Номи категорияи навро ворид кунед (Масалан: `🧥 Курткаҳо`):", reply_markup=back_kb())
    await state.set_state(AdminState.ADD_CATEGORY)

@dp.message(AdminState.ADD_CATEGORY)
async def save_add_cat(message: types.Message, state: FSMContext):
    conn = get_db()
    conn.execute("INSERT INTO categories (name_tj) VALUES (?)", (message.text.strip(),))
    conn.commit()
    conn.close()
    await message.answer("✅ Категорияи нав илова шуд!", reply_markup=main_customer_kb(message.from_user.id))
    await state.clear()

@dp.callback_query(F.data.startswith("del_cat_"))
async def delete_cat(callback: types.CallbackQuery):
    cat_id = int(callback.data.split("_")[2])
    conn = get_db()
    conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    conn.execute("DELETE FROM products WHERE category_id=?", (cat_id,))
    conn.commit()
    conn.close()
    await callback.answer("🗑 Категория нест карда шуд!", show_alert=True)

# --- MAHSULOT QO'SHISH VA O'CHIRISH ---
@dp.callback_query(F.data.startswith("adm_cat_prods_"))
async def adm_products_manage(callback: types.CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split("_")[3])
    await state.update_data(current_cat_id=cat_id)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM products WHERE category_id=?", (cat_id,))
    prods = cur.fetchall()
    conn.close()

    buttons = []
    for p in prods:
        buttons.append([
            InlineKeyboardButton(text=f"👕 {p[1]}", callback_data="ignore"),
            InlineKeyboardButton(text="🗑 Нест кардан", callback_data=f"del_prod_{p[0]}")
        ])
    
    buttons.append([InlineKeyboardButton(text="➕ Иловаи либоси нав", callback_data="start_add_prod")])
    buttons.append([InlineKeyboardButton(text="⬅️ Ба ақиб", callback_data="cancel_action")])

    await callback.message.edit_text("Либосҳоро идора кунед ё навашро илова кунед:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("del_prod_"))
async def delete_product(callback: types.CallbackQuery):
    p_id = int(callback.data.split("_")[2])
    conn = get_db()
    conn.execute("DELETE FROM products WHERE id=?", (p_id,))
    conn.commit()
    conn.close()
    await callback.answer("🗑 Либос нест карда шуд!", show_alert=True)

@dp.callback_query(F.data == "start_add_prod")
async def adm_start_add_p(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Номи либосро ворид кунед:", reply_markup=back_kb())
    await state.set_state(AdminState.ADD_PROD_NAME)

@dp.message(AdminState.ADD_PROD_NAME)
async def add_p_name(message: types.Message, state: FSMContext):
    await state.update_data(p_name=message.text)
    await message.answer("Нархи либосро нависед (бо сомонӣ):", reply_markup=back_kb())
    await state.set_state(AdminState.ADD_PROD_PRICE)

@dp.message(AdminState.ADD_PROD_PRICE)
async def add_p_price(message: types.Message, state: FSMContext):
    await state.update_data(p_price=float(message.text))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="дона", callback_data="unit_дона"),
         InlineKeyboardButton(text="ҷуфт", callback_data="unit_ҷуфт"),
         InlineKeyboardButton(text="метр", callback_data="unit_метр")],
        [InlineKeyboardButton(text="⬅️ Ба ақиб", callback_data="cancel_action")]
    ])
    await message.answer("Воҳиди андозагириро интихоб кунед:", reply_markup=kb)
    await state.set_state(AdminState.ADD_PROD_UNIT)

@dp.callback_query(AdminState.ADD_PROD_UNIT, F.data.startswith("unit_"))
async def add_p_unit(callback: types.CallbackQuery, state: FSMContext):
    unit = callback.data.split("_")[1]
    await state.update_data(p_unit=unit)
    await callback.message.answer("📏 Андозаи СТАРТИРО ворид кунед (Масалан: `S` ё `40` ё `60kg`):", reply_markup=back_kb())
    await state.set_state(AdminState.ADD_START_SIZE)

@dp.message(AdminState.ADD_START_SIZE)
async def add_start_size(message: types.Message, state: FSMContext):
    await state.update_data(start_size=message.text.strip())
    await message.answer("📏 Андозаи ОХИРИНРО ворид кунед (Масалан: `XXL` ё `52` ё `68kg`):", reply_markup=back_kb())
    await state.set_state(AdminState.ADD_END_SIZE)

@dp.message(AdminState.ADD_END_SIZE)
async def add_end_size(message: types.Message, state: FSMContext):
    await state.update_data(end_size=message.text.strip())
    await message.answer("⚖️ Вазни тахминиро нависед ё 'Идома додан'-ро пахш кунед:", reply_markup=skip_or_back_kb())
    await state.set_state(AdminState.ADD_WEIGHT_INFO)

@dp.callback_query(AdminState.ADD_WEIGHT_INFO, F.data == "skip_step")
async def skip_weight(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(weight_info=None)
    await callback.message.answer("Акси либосро фиристед:", reply_markup=back_kb())
    await state.set_state(AdminState.ADD_PROD_PHOTO)

@dp.message(AdminState.ADD_WEIGHT_INFO)
async def add_weight(message: types.Message, state: FSMContext):
    await state.update_data(weight_info=message.text.strip())
    await message.answer("Акси либосро фиристед:", reply_markup=back_kb())
    await state.set_state(AdminState.ADD_PROD_PHOTO)

@dp.message(AdminState.ADD_PROD_PHOTO, F.photo)
async def add_p_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    
    conn = get_db()
    conn.execute(
        "INSERT INTO products (category_id, name, price, unit, photo_id, start_size, end_size, weight_info) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (data["current_cat_id"], data["p_name"], data["p_price"], data["p_unit"], photo_id, data.get("start_size"), data.get("end_size"), data.get("weight_info"))
    )
    conn.commit()
    conn.close()
    
    await message.answer("✅ Либоси нав сабт шуд!", reply_markup=main_customer_kb(message.from_user.id))
    await state.clear()

@dp.message()
async def unknown_message(message: types.Message):
    await message.answer("❌ Фармони номаълум. Лутфан тугмаҳои менюро истифода баред!")

async def main():
    print("Kiyim Dokoni Boti ishga tushdi!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
