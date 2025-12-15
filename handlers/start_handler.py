from telebot.types import ReplyKeyboardMarkup, KeyboardButton

def start_handler(message, bot):
    """Начальная команда, отправляет кнопку для запроса контакта."""
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    button = KeyboardButton("Поделиться контактами 📱", request_contact=True)
    markup.add(button)

    bot.send_message(
        message.chat.id,
        "Привет, дорогой друг! 👋\n\nЧтобы начать работу с ботом, пожалуйста, поделитесь своим номером телефона. 😄\n\nПожалуйста, нажмите на кнопку ниже, чтобы отправить свой контакт.",
        reply_markup=markup
    )
