import subprocess
import sys
import os
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "Telegram Bot is running!"

@app.route('/health')
def health():
    return "OK", 200

if __name__ == '__main__':
    # Запускаем бота в отдельном процессе
    bot_process = subprocess.Popen(
        [sys.executable, "bot.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    print(f"🤖 Бот запущен в процессе {bot_process.pid}")
    
    # Запускаем Flask
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=False,
        use_reloader=False