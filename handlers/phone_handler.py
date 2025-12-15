import os
from dotenv import load_dotenv
import logging
import telebot
import re

load_dotenv()
PHONE = os.getenv("PHONE")

# Настройка логирования
logger = logging.getLogger(__name__)


def normalize_phone_number(phone_number: str) -> str:
    """
    Нормализует номер телефона, приводя к единому формату.

    Примеры:
        +7 (912) 345-67-89 -> 79123456789
        8 912 345 67 89    -> 79123456789
        +1 234 567 8900    -> 12345678900

    Args:
        phone_number: Номер телефона в любом формате

    Returns:
        str: Нормализованный номер (только цифры, с кодом страны)
    """
    if not phone_number:
        return ""

    # Удаляем все символы кроме цифр и +
    cleaned = re.sub(r'[^\d+]', '', phone_number)

    # Убираем + из начала
    if cleaned.startswith('+'):
        cleaned = cleaned[1:]

    # Если номер начинается с 8 (российский формат), заменяем на 7
    if cleaned.startswith('8') and len(cleaned) == 11:
        cleaned = '7' + cleaned[1:]

    return cleaned


def phone_handler(message, bot):
    """
    Проверяет номер телефона и авторизует пользователя.

    Args:
        message: Сообщение от Telegram с контактом
        bot: Экземпляр бота
    """
    if not message.contact:
        logger.warning(f"Пользователь {message.from_user.id} отправил сообщение без контакта")
        bot.send_message(
            message.chat.id,
            "⚠️ Пожалуйста, используйте кнопку для отправки контакта."
        )
        return

    user_phone = message.contact.phone_number
    user_id = message.from_user.id

    # Нормализуем оба номера
    normalized_user_phone = normalize_phone_number(user_phone)
    normalized_allowed_phone = normalize_phone_number(PHONE)

    logger.info(
        f"Попытка авторизации пользователя {user_id}. "
        f"Номер: {normalized_user_phone[:3]}***{normalized_user_phone[-4:]}"
    )

    if not normalized_allowed_phone:
        logger.error("Переменная окружения PHONE не установлена или пуста!")
        bot.send_message(
            message.chat.id,
            "⚠️ Ошибка конфигурации. Обратитесь к администратору."
        )
        return

    # Сравниваем нормализованные номера
    if normalized_user_phone == normalized_allowed_phone:
        logger.info(f"Пользователь {user_id} успешно авторизован ✅")

        bot.send_message(
            message.chat.id,
            "✅ Доступ разрешен!\n\n"
            "Отлично, теперь вы можете использовать все возможности бота! 🎉\n\n"
            "Нажмите на кнопку ниже, чтобы посмотреть свой инвестиционный портфель 💼"
        )

        # Отправляем кнопку для просмотра портфеля
        markup = telebot.types.InlineKeyboardMarkup()
        button = telebot.types.InlineKeyboardButton(
            "💼 Мой портфель",
            callback_data="view_stocks"
        )
        markup.add(button)

        bot.send_message(
            message.chat.id,
            "Готовы посмотреть свои акции? "
            "Нажмите кнопку ниже! 📊",
            reply_markup=markup
        )
    else:
        logger.warning(
            f"Пользователь {user_id} не прошёл авторизацию ❌. "
            f"Ожидался: {normalized_allowed_phone[:3]}***{normalized_allowed_phone[-4:]}"
        )

        bot.send_message(
            message.chat.id,
            "❌ Номер телефона не совпадает. Доступ закрыт. 😞\n\n"
            "Если вы считаете, что произошла ошибка, "
            "обратитесь к администратору."
        )