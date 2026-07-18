"""Telegram admin commands for configuring the bot without SSH access.

Runs a second, receive-only Bot/Application (TelegramBot only ever sends)
polling for commands in its own thread, restricted to the user's own
TELEGRAM_CHAT_ID. Tags/blacklist changes apply on the next scheduled run
with no restart (config is re-read live, see Config._get). Schedule and
genre-fallback changes need a restart (APScheduler jobs and the parser's
genre mapping are both fixed at process start), so those commands write the
change and then self-SIGTERM to trigger the existing graceful-shutdown path
and let systemd's Restart=always bring the process back up.
"""
import asyncio
import logging
import os
import signal
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

import yaml
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from src.config import config
from src.scheduler import TaskScheduler

if TYPE_CHECKING:
    from src.main import BandcampBot

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "Доступные команды:\n\n"
    "/tags — список тегов\n"
    "/tags_add <тег> — добавить тег\n"
    "/tags_remove <тег> — убрать тег\n\n"
    "/blacklist — список чёрного списка\n"
    "/blacklist_add <тег>\n"
    "/blacklist_remove <тег>\n\n"
    "/schedule — текущее расписание\n"
    "/schedule_set <07:00,10:00,...> — задать времена (перезапуск)\n"
    "/schedule_jitter <минуты> — задать джиттер (перезапуск)\n\n"
    "/genre_list — сопоставления тег → жанр\n"
    "/genre_set <тег> <жанр> — задать сопоставление (перезапуск)\n"
    "/genre_remove <тег> — убрать сопоставление (перезапуск)\n\n"
    "/status — статистика и статус\n"
)


class AdminBot:
    """Telegram-command interface for editing bot config on the fly."""

    OVERRIDES_PATH = Path("config.overrides.yaml")

    def __init__(self, bandcamp_bot: "BandcampBot"):
        self._bandcamp_bot = bandcamp_bot
        self._authorized_chat_id = int(config.telegram.chat_id)
        self._overrides_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._application: Application = (
            ApplicationBuilder().token(config.telegram.bot_token).build()
        )
        for name, handler in (
            ("help", self._cmd_help),
            ("start", self._cmd_help),
            ("tags", self._cmd_tags),
            ("tags_add", self._cmd_tags_add),
            ("tags_remove", self._cmd_tags_remove),
            ("blacklist", self._cmd_blacklist),
            ("blacklist_add", self._cmd_blacklist_add),
            ("blacklist_remove", self._cmd_blacklist_remove),
            ("schedule", self._cmd_schedule),
            ("schedule_set", self._cmd_schedule_set),
            ("schedule_jitter", self._cmd_schedule_jitter),
            ("genre_list", self._cmd_genre_list),
            ("genre_set", self._cmd_genre_set),
            ("genre_remove", self._cmd_genre_remove),
            ("status", self._cmd_status),
        ):
            self._application.add_handler(CommandHandler(name, handler))

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- lifecycle -----------------------------------------------------

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._thread_target, daemon=True, name="AdminBot")
        self._thread.start()
        logger.info("AdminBot thread started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                logger.warning("AdminBot thread did not stop within 10s")
        logger.info("AdminBot stopped")

    def _thread_target(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as e:
            logger.error(f"AdminBot thread crashed: {e}", exc_info=True)

    async def _run(self) -> None:
        # run_polling() installs its own SIGINT/SIGTERM handlers via
        # asyncio.add_signal_handler, which only works on the main thread -
        # it would raise here. Drive the lifecycle manually instead.
        await self._application.initialize()
        await self._application.start()
        await self._application.updater.start_polling()
        try:
            await self._application.bot.set_my_commands([
                ("tags", "Список тегов"),
                ("tags_add", "Добавить тег"),
                ("tags_remove", "Убрать тег"),
                ("blacklist", "Список чёрного списка"),
                ("blacklist_add", "Добавить в чёрный список"),
                ("blacklist_remove", "Убрать из чёрного списка"),
                ("schedule", "Текущее расписание"),
                ("schedule_set", "Задать времена запуска"),
                ("schedule_jitter", "Задать джиттер"),
                ("genre_list", "Сопоставления тег→жанр"),
                ("genre_set", "Задать сопоставление"),
                ("genre_remove", "Убрать сопоставление"),
                ("status", "Статистика и статус"),
                ("help", "Список команд"),
            ])
        except Exception as e:
            logger.warning(f"Could not set bot command list: {e}")

        logger.info("AdminBot polling started")
        while not self._stop_event.is_set():
            await asyncio.sleep(0.5)

        logger.info("AdminBot stopping...")
        await self._application.updater.stop()
        await self._application.stop()
        await self._application.shutdown()

    # -- overrides file (atomic read-modify-write) ----------------------

    def _read_overrides(self) -> Dict[str, Any]:
        if not self.OVERRIDES_PATH.exists():
            return {}
        with open(self.OVERRIDES_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}

    def _write_overrides(self, data: Dict[str, Any]) -> None:
        tmp_path = self.OVERRIDES_PATH.with_suffix('.yaml.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
        os.replace(tmp_path, self.OVERRIDES_PATH)

    # -- auth ------------------------------------------------------------

    def _is_authorized(self, update: Update) -> bool:
        chat = update.effective_chat
        if chat is None or chat.id != self._authorized_chat_id:
            logger.warning(f"Ignoring admin command from unauthorized chat {chat.id if chat else None}")
            return False
        return True

    async def _request_restart(self, update: Update, message: str) -> None:
        await update.message.reply_text(
            f"✅ {message}\n⏳ Перезапускаю сервис для применения (~10-15 сек)..."
        )
        logger.info("Admin command requested a restart to apply config changes")
        os.kill(os.getpid(), signal.SIGTERM)

    # -- tags / blacklist (no restart needed) ---------------------------

    async def _cmd_tags(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        tags = config.tags
        text = "\n".join(f"- {t}" for t in tags) if tags else "(пусто)"
        await update.message.reply_text(f"Текущие теги:\n{text}")

    async def _cmd_tags_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        if not context.args:
            await update.message.reply_text("Использование: /tags_add <тег>")
            return
        tag = " ".join(context.args).strip()
        with self._overrides_lock:
            data = self._read_overrides()
            tags = list(data.get("tags") or config.tags)
            if tag in tags:
                await update.message.reply_text(f"Тег '{tag}' уже есть.")
                return
            tags.append(tag)
            data["tags"] = tags
            self._write_overrides(data)
        await update.message.reply_text(
            f"✅ Тег '{tag}' добавлен. Применится со следующего запуска (без перезапуска)."
        )

    async def _cmd_tags_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        if not context.args:
            await update.message.reply_text("Использование: /tags_remove <тег>")
            return
        tag = " ".join(context.args).strip()
        with self._overrides_lock:
            data = self._read_overrides()
            tags = list(data.get("tags") or config.tags)
            if tag not in tags:
                await update.message.reply_text(f"Тег '{tag}' не найден.")
                return
            tags.remove(tag)
            data["tags"] = tags
            self._write_overrides(data)
        await update.message.reply_text(
            f"✅ Тег '{tag}' убран. Применится со следующего запуска (без перезапуска)."
        )

    async def _cmd_blacklist(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        tags = config.blacklist_tags
        text = "\n".join(f"- {t}" for t in tags) if tags else "(пусто)"
        await update.message.reply_text(f"Чёрный список:\n{text}")

    async def _cmd_blacklist_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        if not context.args:
            await update.message.reply_text("Использование: /blacklist_add <тег>")
            return
        tag = " ".join(context.args).strip()
        with self._overrides_lock:
            data = self._read_overrides()
            tags = list(data.get("blacklist_tags") or config.blacklist_tags)
            if tag in tags:
                await update.message.reply_text(f"'{tag}' уже в чёрном списке.")
                return
            tags.append(tag)
            data["blacklist_tags"] = tags
            self._write_overrides(data)
        await update.message.reply_text(
            f"✅ '{tag}' добавлен в чёрный список. Применится со следующего запуска."
        )

    async def _cmd_blacklist_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        if not context.args:
            await update.message.reply_text("Использование: /blacklist_remove <тег>")
            return
        tag = " ".join(context.args).strip()
        with self._overrides_lock:
            data = self._read_overrides()
            tags = list(data.get("blacklist_tags") or config.blacklist_tags)
            if tag not in tags:
                await update.message.reply_text(f"'{tag}' не в чёрном списке.")
                return
            tags.remove(tag)
            data["blacklist_tags"] = tags
            self._write_overrides(data)
        await update.message.reply_text(
            f"✅ '{tag}' убран из чёрного списка. Применится со следующего запуска."
        )

    # -- schedule (restart needed) ---------------------------------------

    async def _cmd_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        s = config.schedule
        await update.message.reply_text(
            f"Расписание: {', '.join(s.times)}\n"
            f"Часовой пояс: {s.timezone}\n"
            f"Джиттер: {s.jitter_minutes} мин"
        )

    async def _cmd_schedule_set(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        if not context.args:
            await update.message.reply_text("Использование: /schedule_set 07:00,10:00,13:00")
            return
        times = [t.strip() for t in " ".join(context.args).split(",") if t.strip()]
        for t in times:
            try:
                TaskScheduler.parse_time(t)
            except ValueError as e:
                await update.message.reply_text(f"❌ {e}")
                return
        with self._overrides_lock:
            data = self._read_overrides()
            schedule = dict(data.get("schedule") or {})
            schedule["times"] = times
            data["schedule"] = schedule
            self._write_overrides(data)
        await self._request_restart(update, f"Расписание обновлено: {', '.join(times)}.")

    async def _cmd_schedule_jitter(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        if not context.args or not context.args[0].isdigit():
            await update.message.reply_text("Использование: /schedule_jitter <минуты>")
            return
        minutes = int(context.args[0])
        with self._overrides_lock:
            data = self._read_overrides()
            schedule = dict(data.get("schedule") or {})
            schedule["jitter_minutes"] = minutes
            data["schedule"] = schedule
            self._write_overrides(data)
        await self._request_restart(update, f"Джиттер обновлён: {minutes} мин.")

    # -- genre fallback mapping (restart needed) -------------------------

    async def _cmd_genre_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        mapping = config.genre_fallback
        lines = [f"{tag} → {genre}" for tag, genre in sorted(mapping.items())]
        await update.message.reply_text("Сопоставления тег → жанр:\n" + "\n".join(lines))

    async def _cmd_genre_set(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        if len(context.args) < 2:
            await update.message.reply_text("Использование: /genre_set <тег> <жанр>")
            return
        genre = context.args[-1].strip()
        tag = " ".join(context.args[:-1]).strip()
        with self._overrides_lock:
            data = self._read_overrides()
            # Patch dict (tag -> genre or None-tombstone), not the full
            # merged mapping - config.genre_fallback layers this on top of
            # BandcampParser.GENRE_FALLBACK at read time.
            genre_map = dict(data.get("genre_fallback") or {})
            genre_map[tag] = genre
            data["genre_fallback"] = genre_map
            self._write_overrides(data)
        await self._request_restart(update, f"'{tag}' → '{genre}' сохранено.")

    async def _cmd_genre_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        if not context.args:
            await update.message.reply_text("Использование: /genre_remove <тег>")
            return
        tag = " ".join(context.args).strip()
        with self._overrides_lock:
            data = self._read_overrides()
            genre_map = dict(data.get("genre_fallback") or {})
            genre_map[tag] = None  # tombstone
            data["genre_fallback"] = genre_map
            self._write_overrides(data)
        await self._request_restart(update, f"'{tag}' убран из сопоставлений.")

    # -- status (read-only) ----------------------------------------------

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        stats = self._bandcamp_bot.db.get_stats()
        disk_pct = self._bandcamp_bot.db.disk_usage_percent()
        last_run = self._bandcamp_bot._last_run_at
        last_run_str = last_run.strftime('%Y-%m-%d %H:%M UTC') if last_run else "ещё не было"
        await update.message.reply_text(
            f"📊 Релизов в БД: {stats.total} (отправлено: {stats.sent}, ожидает: {stats.pending})\n"
            f"💾 Диск: {disk_pct:.1f}% занято\n"
            f"🕒 Последний успешный запуск: {last_run_str}"
        )

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        await update.message.reply_text(HELP_TEXT)
