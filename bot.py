import logging
import sqlite3
import time
import sys
import os
import datetime
import threading
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CREATOR_ID = os.environ.get('CREATOR_ID')

if not TOKEN:
    print("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не установлен в переменных окружения!")
    print("Добавьте переменную TELEGRAM_BOT_TOKEN в настройках Render")
    sys.exit(1)

LOG_CLEANUP_HOURS = 24
LOG_RETENTION_DAYS = 7
HEARTBEAT_INTERVAL = 300

os.makedirs('logs', exist_ok=True)
os.makedirs('logs/archive', exist_ok=True)

LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

# Настройка логгера
log_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Основной обработчик логов
main_log_handler = RotatingFileHandler(
    'logs/bot_main.log',
    maxBytes=5*1024*1024,
    backupCount=10
)
main_log_handler.setFormatter(log_formatter)

# Обработчик ошибок
error_log_handler = RotatingFileHandler(
    'logs/bot_errors.log',
    maxBytes=2*1024*1024,
    backupCount=5
)
error_log_handler.setFormatter(log_formatter)
error_log_handler.setLevel(logging.ERROR)

# Консольный обработчик
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)

# Настройка корневого логгера
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(main_log_handler)
logger.addHandler(error_log_handler)
logger.addHandler(console_handler)

bot_logger = logging.getLogger(__name__)

class BotMonitor:
    """Мониторинг и обслуживание бота"""

    def __init__(self):
        self.start_time = time.time()
        self.message_count = 0
        self.last_cleanup = time.time()
        self.last_heartbeat = time.time()
        self.running = True

    def increment_message_count(self):
        self.message_count += 1

    def get_uptime(self):
        uptime = time.time() - self.start_time
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        seconds = int(uptime % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def cleanup_old_logs(self):
        """Очистка старых логов"""
        try:
            current_time = time.time()
            cutoff_time = current_time - (LOG_RETENTION_DAYS * 86400)

            deleted_count = 0
            for filename in os.listdir('logs'):
                if filename.endswith('.log'):
                    filepath = os.path.join('logs', filename)
                    if os.path.getmtime(filepath) < cutoff_time:
                        try:
                            os.remove(filepath)
                            deleted_count += 1
                            bot_logger.info(f"Удален старый лог: {filename}")
                        except Exception as e:
                            bot_logger.warning(f"Не удалось удалить {filename}: {e}")

            # Архивируем текущий основной лог если он больше 1MB
            main_log_path = 'logs/bot_main.log'
            if os.path.exists(main_log_path) and os.path.getsize(main_log_path) > 1024*1024:
                try:
                    archive_name = f"logs/archive/bot_main_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
                    os.rename(main_log_path, archive_name)
                    bot_logger.info(f"Основной лог заархивирован: {archive_name}")
                except Exception as e:
                    bot_logger.error(f"Ошибка архивации лога: {e}")

            self.last_cleanup = current_time
            if deleted_count > 0:
                bot_logger.info(f"Очистка логов завершена. Удалено: {deleted_count} файлов")

        except Exception as e:
            bot_logger.error(f"Ошибка при очистке логов: {e}")

    def send_heartbeat(self):
        """Отправка heartbeat для поддержания активности"""
        try:
            uptime = self.get_uptime()
            log_size = 0
            if os.path.exists('logs/bot_main.log'):
                log_size = os.path.getsize('logs/bot_main.log') / 1024
            
            stats = (f"🤖 Бот работает\n"
                    f"⏱ Время работы: {uptime}\n"
                    f"📊 Сообщений обработано: {self.message_count}\n"
                    f"💾 Лог: {log_size:.1f} KB")

            bot_logger.info(f"Heartbeat: {stats}")
            self.last_heartbeat = time.time()

        except Exception as e:
            bot_logger.error(f"Ошибка heartbeat: {e}")

# Глобальный монитор
monitor = BotMonitor()

def schedule_cleanup():
    """Планировщик очистки логов"""
    while monitor.running:
        try:
            current_time = time.time()

            # Проверяем нужно ли очистить логи
            if current_time - monitor.last_cleanup > (LOG_CLEANUP_HOURS * 3600):
                monitor.cleanup_old_logs()

            # Отправляем heartbeat
            if current_time - monitor.last_heartbeat > HEARTBEAT_INTERVAL:
                monitor.send_heartbeat()

            time.sleep(60)

        except Exception as e:
            bot_logger.error(f"Ошибка в планировщике: {e}")
            time.sleep(300)

def format_time_remaining(hours, minutes):
    if hours > 0:
        if hours == 1 or hours == 21:
            hours_text = f"{hours} час"
        elif 2 <= hours <= 4 or 22 <= hours <= 24:
            hours_text = f"{hours} часа"
        else:
            hours_text = f"{hours} часов"

    if minutes > 0:
        if minutes == 1 or minutes == 21 or minutes == 31 or minutes == 41 or minutes == 51:
            minutes_text = f"{minutes} минуту"
        elif (2 <= minutes <= 4 or 22 <= minutes <= 24 or
              32 <= minutes <= 34 or 42 <= minutes <= 44 or
              52 <= minutes <= 54):
            minutes_text = f"{minutes} минуты"
        else:
            minutes_text = f"{minutes} минут"

    if hours > 0 and minutes > 0:
        return f"{hours_text} {minutes_text}"
    elif hours > 0:
        return hours_text
    elif minutes > 0:
        return minutes_text
    else:
        return "0 минут"

def init_database():
    try:
        conn = sqlite3.connect('user_limits.db')
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_limits (
                user_id INTEGER PRIMARY KEY,
                last_message_time INTEGER
            )
        ''')

        conn.commit()
        conn.close()
        bot_logger.info("✅ База данных инициализирована")
    except Exception as e:
        bot_logger.error(f"❌ Ошибка инициализации базы данных: {e}")
        # Не завершаем работу, пробуем продолжить

def can_send_message(user_id):
    try:
        conn = sqlite3.connect('user_limits.db')
        cursor = conn.cursor()

        cursor.execute(
            'SELECT last_message_time FROM user_limits WHERE user_id = ?',
            (user_id,)
        )

        result = cursor.fetchone()
        conn.close()

        if result is None:
            return True

        last_message_time = result[0]
        current_time = int(time.time())

        return (current_time - last_message_time) >= 86400
    except Exception as e:
        bot_logger.error(f"Ошибка проверки лимита для user {user_id}: {e}")
        return True  # В случае ошибки разрешаем отправить сообщение

def save_message_time(user_id):
    try:
        conn = sqlite3.connect('user_limits.db')
        cursor = conn.cursor()

        current_time = int(time.time())

        cursor.execute('''
            INSERT OR REPLACE INTO user_limits (user_id, last_message_time)
            VALUES (?, ?)
        ''', (user_id, current_time))

        conn.commit()
        conn.close()
    except Exception as e:
        bot_logger.error(f"Ошибка сохранения времени для user {user_id}: {e}")

def get_time_until_next_message(user_id):
    try:
        conn = sqlite3.connect('user_limits.db')
        cursor = conn.cursor()

        cursor.execute(
            'SELECT last_message_time FROM user_limits WHERE user_id = ?',
            (user_id,)
        )

        result = cursor.fetchone()
        conn.close()

        if result is None:
            return 0, 0

        last_message_time = result[0]
        current_time = int(time.time())
        time_passed = current_time - last_message_time

        if time_passed >= 86400:
            return 0, 0

        time_remaining = 86400 - time_passed

        hours = time_remaining // 3600
        minutes = (time_remaining % 3600) // 60

        if time_remaining % 60 > 0:
            minutes += 1
            if minutes == 60:
                hours += 1
                minutes = 0

        return hours, minutes
    except Exception as e:
        bot_logger.error(f"Ошибка расчета времени для user {user_id}: {e}")
        return 24, 0  # В случае ошибки возвращаем полный период

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        'Добро пожаловать!\n\n'
        'Отправь мне текстовое сообщение, и оно опубликуется в канал "мир знает, что".\n\n'
    )
    await update.message.reply_text(welcome_text)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    if not can_send_message(user_id):
        hours, minutes = get_time_until_next_message(user_id)

        time_text = format_time_remaining(hours, minutes)

        limit_text = (
            f"Следующее сообщение можно отправить через:\n"
            f"{time_text}"
        )

        await update.message.reply_text(limit_text)
        return

    if not update.message.text or update.message.text.isspace():
        await update.message.reply_text("Сообщение не может быть пустым.")
        return

    save_message_time(user_id)

    await update.message.reply_text("Сообщение отправлено. Опубликуется в порядке очереди.")

    try:
        user_info = f"@{user.username}" if user.username else f"ID: {user.id}"

        message_to_creator = (
            f"Новое сообщение от {user_info}:"
        )

        await context.bot.send_message(
            chat_id=CREATOR_ID,
            text=message_to_creator
        )

        await context.bot.send_message(
            chat_id=CREATOR_ID,
            text=update.message.text
        )

    except Exception as e:
        await update.message.reply_text("Произошла ошибка.")

async def handle_unsupported_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Принимаются только текстовые сообщения.")

def main():
    try:
        bot_logger.info("=" * 50)
        bot_logger.info("🚀 Запуск Telegram бота")
        bot_logger.info(f"⏰ Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        bot_logger.info("=" * 50)
        
        # Инициализация базы данных
        init_database()
        
        # Оптимизация БД
        try:
            conn = sqlite3.connect('user_limits.db')
            cursor = conn.cursor()
            cursor.execute('PRAGMA optimize')
            cursor.execute('PRAGMA journal_mode=WAL')
            conn.commit()
            conn.close()
            bot_logger.info("✅ База данных оптимизирована")
        except Exception as e:
            bot_logger.warning(f"Не удалось оптимизировать БД: {e}")
        
        # Проверка токена
        if not TOKEN or TOKEN == 'your_bot_token_here':
            bot_logger.error("❌ Токен бота не установлен!")
            bot_logger.error("Добавьте TELEGRAM_BOT_TOKEN в переменные окружения Render")
            return
        
        bot_logger.info(f"✅ Токен получен (длина: {len(TOKEN)})")
        
        # Создание приложения
        application = Application.builder().token(TOKEN).build()
        
        # Добавление обработчиков
        application.add_handler(CommandHandler("start", start))
        
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text_message
        ))
        
        application.add_handler(MessageHandler(
            ~filters.TEXT & ~filters.COMMAND,
            handle_unsupported_message
        ))
        
        # Запуск планировщика очистки в отдельном потоке
        cleanup_thread = threading.Thread(target=schedule_cleanup, daemon=True)
        cleanup_thread.start()
        bot_logger.info("✅ Планировщик очистки логов запущен")
        
        bot_logger.info("✅ Бот запущен и готов к работе")
        bot_logger.info(f"👤 ID создателя: {CREATOR_ID}")
        
        # Запуск бота с перезапуском при ошибках
        bot_logger.info("🔄 Запуск polling...")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            close_loop=False
        )
        
    except KeyboardInterrupt:
        bot_logger.info("⏹ Остановка бота по запросу пользователя")
        monitor.running = False
    except Exception as e:
        bot_logger.error(f"💥 Критическая ошибка при запуске: {e}")
        import traceback
        bot_logger.error(traceback.format_exc())

if __name__ == '__main__':
    main()