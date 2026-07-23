# 🍕 Restaurant & Delivery Telegram Bot (aiogram 3.x)

[English](#english) | [Тоҷикӣ](#тоҷикӣ)

---

## English

A fully asynchronous, high-performance Telegram Bot for restaurants, cafes, and food delivery services built with **Python 3.11+**, **aiogram 3.x**, and **aiosqlite**.

### ✨ Features
* 🛒 **Interactive Shopping Cart:** Multi-item basket system (add, view, and clear products).
* 📍 **Geolocation Validation:** Calculates delivery distance (Haversine formula) and validates coordinates against configured limits.
* 💳 **Payment Receipt System:** Customers upload payment receipt screenshots for admin verification.
* ⚙️ **Admin Control Panel:**
  * Manage categories & products (photos, pricing, descriptions).
  * Real-time Stock/Stop-List toggling (🟢 In Stock / 🔴 Out of Stock).
  * Order Approval & Rejection workflow with notification alerts.
  * Broadcast notification system to all users.
  * Geolocation & Payment details configuration.
* ⚡ **Asynchronous Architecture:** Non-blocking I/O operations using `aiosqlite` and `aiogram 3.x`.

### 🚀 Quick Start

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/ibroximxudoyqulov/restaurant-telegram-bot.git](https://github.com/ibroximxudoyqulov/restaurant-telegram-bot.git)
   cd restaurant-telegram-bot
