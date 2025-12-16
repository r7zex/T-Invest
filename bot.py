import telebot
from dotenv import load_dotenv
import os
import logging
import sys
from handlers.start_handler import start_handler
from handlers.phone_handler import phone_handler
from handlers.stock_handler import handle_stock_callback
from datetime import datetime

# Получаем текущую дату и время
current_time = datetime.now()
date_str = current_time.strftime('%Y-%m-%d')  # Форматируем текущую дату
hour_str = current_time.strftime('%H')  # Форматируем текущий час

# Создаем путь до папки для логов с разделением по дням и часам
log_dir = 'logs'
day_dir = os.path.join(log_dir, date_str)  # Папка для конкретного дня
hour_dir = os.path.join(day_dir, hour_str)  # Папка для конкретного часа

# Проверяем и создаем все необходимые папки
os.makedirs(hour_dir, exist_ok=True)

# Настройка логирования с уникальными именами файлов
log_filename = f"{current_time.strftime('%H-%M-%S')}_bot.log"  # Имя файла с временем
log_filepath = os.path.join(hour_dir, log_filename)  # Полный путь до файла лога

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_filepath, encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

logger.info(f"Логирование запущено. Логи будут сохраняться в: {log_filepath}")

# Загружаем переменные окружения
load_dotenv()

# Проверяем наличие необходимых переменных
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
T_INVEST_API_KEY = os.getenv("T_INVEST_API_KEY")
PHONE = os.getenv("PHONE")

if not TELEGRAM_TOKEN:
    logger.error("❌ Ошибка: TELEGRAM_TOKEN не установлен в .env файле!")
    sys.exit(1)

if not T_INVEST_API_KEY:
    logger.error("❌ Ошибка: T_INVEST_API_KEY не установлен в .env файле!")
    sys.exit(1)

if not PHONE:
    logger.error("❌ Ошибка: PHONE не установлен в .env файле!")
    sys.exit(1)

# Создаём объект бота
bot = telebot.TeleBot(TELEGRAM_TOKEN)


@bot.message_handler(commands=['start'])
def start(message):
    """Обработчик команды /start"""
    logger.info(f"Пользователь {message.from_user.id} начал разговор с ботом")
    start_handler(message, bot)


@bot.message_handler(content_types=['contact'])
def phone(message):
    """Обработчик получения контакта"""
    logger.info(f"Получен контакт от пользователя {message.from_user.id}")
    phone_handler(message, bot)


@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    """Обработчик всех callback запросов"""
    logger.info(
        f"Пользователь {call.from_user.id} "
        f"выполнил действие: {call.data}"
    )
    handle_stock_callback(call, bot)


@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Обработчик всех остальных сообщений"""
    logger.info(
        f"Получено необработанное сообщение от {message.from_user.id}: "
        f"{message.text if message.text else '[не текст]'}"
    )

    bot.send_message(
        message.chat.id,
        "🤔 Я не понимаю эту команду.\n\n"
        "Используйте /start для начала работы."
    )


def main():
    """Основная функция запуска бота"""
    logger.info("=" * 50)
    logger.info("💼 T-Invest Portfolio Bot запущен 🟢")
    logger.info("=" * 50)

    try:
        # Запуск бота с обработкой ошибок
        bot.infinity_polling(
            timeout=60,
            long_polling_timeout=60,
            logger_level=logging.INFO
        )
    except KeyboardInterrupt:
        logger.info("🛑 Получен сигнал остановки (Ctrl+C)")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
    finally:
        logger.info("👋 Бот остановлен")


if __name__ == '__main__':
    main()