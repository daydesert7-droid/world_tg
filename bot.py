import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import time

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Получаем токен из переменных окружения
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CREATOR_ID = os.environ.get('CREATOR_ID')

# Проверка токена
if not TOKEN:
    logger.error("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не установлен!")
    logger.error("Добавьте переменную TELEGRAM_BOT_TOKEN в настройках Render")
    exit(1)

# Временное хранилище в памяти (вместо SQLite)
user_limits = {}

def format_time_remaining(seconds):
    """Форматирование времени оставшегося до следующего сообщения"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    
    if hours > 0:
        if hours == 1 or hours == 21:
            hours_text = f"{hours} час"
        elif 2 <= hours <= 4 or 22 <= hours <= 24:
            hours_text = f"{hours} часа"
        else:
            hours_text = f"{hours} часов"
    else:
        hours_text = ""

    if minutes > 0:
        if minutes == 1 or minutes == 21 or minutes == 31 or minutes == 41 or minutes == 51:
            minutes_text = f"{minutes} минуту"
        elif (2 <= minutes <= 4 or 22 <= minutes <= 24 or
              32 <= minutes <= 34 or 42 <= minutes <= 44 or
              52 <= minutes <= 54):
            minutes_text = f"{minutes} минуты"
        else:
            minutes_text = f"{minutes} минут"
    else:
        minutes_text = ""

    if hours > 0 and minutes > 0:
        return f"{hours_text} {minutes_text}"
    elif hours > 0:
        return hours_text
    elif minutes > 0:
        return minutes_text
    else:
        return "0 минут"

def can_send_message(user_id):
    """Проверяет, может ли пользователь отправить сообщение"""
    user_id_str = str(user_id)
    
    if user_id_str not in user_limits:
        return True

    last_message_time = user_limits[user_id_str]
    current_time = int(time.time())

    return (current_time - last_message_time) >= 86400

def save_message_time(user_id):
    """Сохраняет время отправки сообщения"""
    user_id_str = str(user_id)
    current_time = int(time.time())
    user_limits[user_id_str] = current_time
    logger.info(f"Сохранено время для пользователя {user_id}")

def get_time_until_next_message(user_id):
    """Возвращает оставшееся время до следующего сообщения в секундах"""
    user_id_str = str(user_id)
    
    if user_id_str not in user_limits:
        return 0

    last_message_time = user_limits[user_id_str]
    current_time = int(time.time())
    time_passed = current_time - last_message_time

    if time_passed >= 86400:
        return 0

    return 86400 - time_passed

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    welcome_text = (
        'Добро пожаловать!\n\n'
        'Отправь мне текстовое сообщение, и оно опубликуется в канал "мир знает, что".'
    )
    await update.message.reply_text(welcome_text)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user = update.effective_user
    user_id = user.id
    
    if not can_send_message(user_id):
        seconds_left = get_time_until_next_message(user_id)
        time_text = format_time_remaining(seconds_left)

        limit_text = (
            f"Следующее сообщение можно отправить через:\n"
            f"{time_text}"
        )

        await update.message.reply_text(limit_text, parse_mode='Markdown')
        return

    if not update.message.text or update.message.text.isspace():
        await update.message.reply_text("Сообщение не может быть пустым.")
        return

    save_message_time(user_id)

    await update.message.reply_text(
        "Сообщение отправлено. Опубликуется в порядке очереди."
    )

    try:
        user_info = f"@{user.username}" if user.username else f"ID: {user.id}"
        
        # Получаем текущее время в формате строки
        current_time = time.strftime('%Y-%m-%d %H:%M:%S')
        
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

        logger.info(f"Сообщение от пользователя {user_id} отправлено создателю")

    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения создателю: {e}")
        await update.message.reply_text("⚠ Произошла ошибка при обработке сообщения.")

async def handle_unsupported_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик неподдерживаемых типов сообщений"""
    await update.message.reply_text(
        "Принимаются только текстовые сообщения."
    )

async def main():
    """Основная асинхронная функция запуска бота"""
    try:
        logger.info("=" * 50)
        logger.info("🚀 Запуск Telegram бота")
        logger.info(f"⏰ Время запуска: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 50)
        
        logger.info(f"✅ Токен получен (длина: {len(TOKEN)})")
        logger.info(f"👤 ID создателя: {CREATOR_ID}")
        
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
        
        logger.info(f"📊 Пользователей в памяти: {len(user_limits)}")
        logger.info("✅ Бот запущен и готов к работе")
        logger.info("🔄 Запуск polling...")
        
        # Запуск polling
        await application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            close_loop=False
        )
        
    except KeyboardInterrupt:
        logger.info("⏹ Остановка бота по запросу пользователя")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка при запуске: {e}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == '__main__':
    asyncio.run(main())