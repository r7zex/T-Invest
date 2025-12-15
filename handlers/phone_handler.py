import os
from dotenv import load_dotenv
import logging
import telebot

load_dotenv()
PHONE = os.getenv("PHONE")

# Настроим логирование
logger = logging.getLogger(__name__)

def clean_phone_number(phone_number):
    """Очистка номера телефона от лишних символов."""
    return ''.join(char for char in phone_number if char.isdigit())  # Оставляем только цифры

def phone_handler(message, bot):
    """Проверка номера телефона и авторизация пользователя."""
    user_phone = message.contact.phone_number
    cleaned_user_phone = clean_phone_number(user_phone)  # Очищаем номер от лишних символов
    cleaned_phone = clean_phone_number(PHONE)  # Очищаем номер из .env

    if cleaned_user_phone == cleaned_phone:
        logger.info(f"Пользователь {message.from_user.id} успешно авторизовался ✅")
        bot.send_message(
            message.chat.id,
            "✅ Доступ разрешен! Отлично, теперь вы можете использовать все возможности бота! 🎉\n\nНажмите на кнопку ниже, чтобы посмотреть доступные акции 📊"
        )

        # Отправка кнопки "Посмотреть акции"
        markup = telebot.types.InlineKeyboardMarkup()
        button = telebot.types.InlineKeyboardButton("Посмотреть акции 📈", callback_data="view_stocks")
        markup.add(button)
        bot.send_message(message.chat.id, "Вы готовы к следующему шагу? Нажмите кнопку ниже, чтобы просмотреть акции!", reply_markup=markup)

    else:
        logger.warning(f"Пользователь {message.from_user.id} не прошел авторизацию ❌")
        bot.send_message(message.chat.id, "❌ Номер телефона не совпадает. Доступ закрыт. 😞")
