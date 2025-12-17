import threading
import os
import time
from flask import Flask

# Импортируем только необходимые функции из bot.py
# ВАЖНО: НЕ импортируем main(), чтобы избежать дублирования запуска
from bot import (
    monitor,  # объект мониторинга
    schedule_cleanup,  # функция планировщика
    init_database,  # функция инициализации БД
    format_time_remaining,
    can_send_message,
    save_message_time,
    get_time_until_next_message,
    start as bot_start,
    handle_text_message,
    handle_unsupported_message
)

app = Flask(__name__)

# Глобальные флаги для управления потоками
bot_running = False
cleanup_thread = None

def start_bot_without_polling():
    """
    Запускаем логику бота без polling
    Polling будет запущен через отдельный импорт
    """
    global bot_running
    
    if bot_running:
        print("⚠️ Бот уже запущен")
        return
    
    try:
        print("🔄 Инициализация компонентов бота...")
        
        # Инициализация БД
        init_database()
        
        # Запуск планировщика очистки
        global cleanup_thread
        if cleanup_thread is None or not cleanup_thread.is_alive():
            cleanup_thread = threading.Thread(target=schedule_cleanup, daemon=True)
            cleanup_thread.start()
            print("✅ Планировщик очистки запущен")
        
        bot_running = True
        print("✅ Компоненты бота инициализированы")
        
    except Exception as e:
        print(f"❌ Ошибка инициализации бота: {e}")
        import traceback
        traceback.print_exc()

@app.route('/')
def home():
    uptime = "Неизвестно"
    if hasattr(monitor, 'get_uptime'):
        uptime = monitor.get_uptime()
    
    return f"""
    <html>
        <head>
            <title>Telegram Bot Status</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }}
                .status {{ padding: 15px; border-radius: 5px; margin: 10px 0; }}
                .running {{ background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }}
                .info {{ background-color: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }}
            </style>
        </head>
        <body>
            <h1>🤖 Telegram Bot Status</h1>
            <div class="status running">
                <strong>✅ Статус:</strong> Работает
            </div>
            <div class="status info">
                <strong>⏱ Время работы:</strong> {uptime}<br>
                <strong>📊 Сообщений обработано:</strong> {monitor.message_count if hasattr(monitor, 'message_count') else 0}<br>
                <strong>🔄 Последнее обновление:</strong> {time.strftime('%Y-%m-%d %H:%M:%S')}
            </div>
            <p>
                <a href="/health">Проверка здоровья</a> | 
                <a href="/status">Детальный статус</a>
            </p>
        </body>
    </html>
    """

@app.route('/health')
def health():
    """Endpoint для health-check (используется Render и UptimeRobot)"""
    try:
        # Проверяем, что бот инициализирован
        if not bot_running:
            return "Bot not initialized", 503
        
        return "OK", 200
    except Exception as e:
        return f"ERROR: {str(e)}", 500

@app.route('/status')
def status():
    """Детальная информация о статусе бота"""
    status_info = {
        "bot_running": bot_running,
        "cleanup_thread_alive": cleanup_thread.is_alive() if cleanup_thread else False,
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        "monitor_available": hasattr(monitor, 'get_uptime')
    }
    
    if hasattr(monitor, 'get_uptime'):
        status_info["uptime"] = monitor.get_uptime()
        status_info["message_count"] = monitor.message_count
    
    import json
    return json.dumps(status_info, indent=2, ensure_ascii=False)

def start_polling_in_separate_process():
    """
    Запускает polling бота в отдельном ПРОЦЕССЕ (не потоке)
    Это нужно, чтобы избежать конфликта с Flask
    """
    import subprocess
    import sys
    
    print("🚀 Запуск Telegram бота в отдельном процессе...")
    
    # Запускаем бота в отдельном процессе
    process = subprocess.Popen(
        [sys.executable, "-c", """
import asyncio
import sys
import os
sys.path.insert(0, os.getcwd())

from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
from bot import TOKEN, CREATOR_ID, init_database, format_time_remaining
from bot import can_send_message, save_message_time, get_time_until_next_message
from bot import start as bot_start, handle_text_message, handle_unsupported_message
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    try:
        logger.info("🤖 Запуск Telegram бота в отдельном процессе...")
        
        if not TOKEN:
            logger.error("❌ Токен бота не найден!")
            return
        
        # Создание приложения
        application = Application.builder().token(TOKEN).build()
        
        # Добавление обработчиков
        application.add_handler(CommandHandler("start", bot_start))
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text_message
        ))
        application.add_handler(MessageHandler(
            ~filters.TEXT & ~filters.COMMAND,
            handle_unsupported_message
        ))
        
        logger.info("✅ Бот инициализирован. Запуск polling...")
        
        # Запуск polling
        await application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            close_loop=False
        )
        
    except Exception as e:
        logger.error(f"💥 Ошибка в процессе бота: {e}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(main())
        """],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Записываем вывод в логи
    import threading as thr
    
    def log_output(pipe, prefix):
        for line in pipe:
            print(f"{prefix}: {line.strip()}")
    
    thr.Thread(target=log_output, args=(process.stdout, "BOT-STDOUT"), daemon=True).start()
    thr.Thread(target=log_output, args=(process.stderr, "BOT-STDERR"), daemon=True).start()
    
    return process

if __name__ == '__main__':
    print("=" * 50)
    print("🚀 Запуск Flask сервера для Telegram бота")
    print("=" * 50)
    
    # Запускаем компоненты бота (без polling)
    start_bot_without_polling()
    
    # Запускаем polling в отдельном процессе
    bot_process = start_polling_in_separate_process()
    
    print(f"📊 PID процесса бота: {bot_process.pid}")
    print(f"🌐 Flask запускается на http://0.0.0.0:5000")
    print(f"🔧 Health check: http://0.0.0.0:5000/health")
    print("=" * 50)
    
    try:
        # Запускаем Flask
        app.run(
            host='0.0.0.0', 
            port=int(os.environ.get('PORT', 5000)), 
            debug=False, 
            use_reloader=False
        )
    except KeyboardInterrupt:
        print("\n⏹ Остановка сервера...")
        if bot_process:
            bot_process.terminate()
    except Exception as e:
        print(f"❌ Ошибка запуска Flask: {e}")
        if bot_process:
            bot_process.terminate()