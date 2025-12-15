import telebot
from dotenv import load_dotenv
import os
import logging
from handlers.start_handler import start_handler
from handlers.phone_handler import phone_handler
from handlers.stock_handler import stock_handler

# Настроим логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загружаем переменные окружения
load_dotenv()

# Получаем токен бота из переменной окружения
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Создаем объект бота
bot = telebot.TeleBot(TOKEN)

# Стартовая команда бота
@bot.message_handler(commands=['start'])
def start(message):
    logger.info(f"Пользователь {message.from_user.id} начал разговор с ботом.")
    start_handler(message, bot)

# Обработчик получения телефона
@bot.message_handler(content_types=['contact'])
def phone(message):
    logger.info(f"Получен контакт от пользователя {message.from_user.id}.")
    phone_handler(message, bot)

# Обработчик запросов по акциям
@bot.callback_query_handler(func=lambda call: True)
def stock(call):
    logger.info(f"Пользователь {call.from_user.id} сделал запрос по акциям.")
    stock_handler(call, bot)

# Запуск бота
if __name__ == '__main__':
    logger.info("Бот запущен 🟢")
    bot.polling(none_stop=True)
