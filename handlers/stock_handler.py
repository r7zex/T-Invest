import telebot
import logging
from utils.api_client import fetch_shares

logger = logging.getLogger(__name__)

def stock_handler(call, bot):
    """Обработка callback для списка акций."""
    if call.data == "view_stocks":
        logger.info(f"Пользователь {call.from_user.id} запросил список акций 📊")

        # Удаляем предыдущее сообщение
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass

        # Получаем акции через T‑Invest API
        shares = fetch_shares()

        if not shares:
            bot.send_message(
                call.message.chat.id,
                "⚠️ Не удалось получить данные об акциях 😕\n"
                "Попробуйте позже или убедитесь, что API‑токен действителен."
            )
            return

        # Формируем инлайн‑кнопки с акциями по 3 в ряд
        markup = telebot.types.InlineKeyboardMarkup(row_width=3)
        for s in shares:
            # Получаем тикер акции
            ticker = s.get("ticker") or s.get("name") or "–"
            figi = s.get("figi") or ticker
            btn = telebot.types.InlineKeyboardButton(
                f"{ticker}", callback_data=f"stock_select::{figi}"
            )
            markup.add(btn)

        bot.send_message(
            call.message.chat.id,
            "📄 Вот список доступных акций 📈\nВыберите ту, по которой хотите получить данные:",
            reply_markup=markup
        )

    # Нажали на конкретную акцию – заглушка
    elif call.data.startswith("stock_select::"):
        figi = call.data.split("::")[1]
        logger.info(f"Пользователь {call.from_user.id} выбрал акцию FIGI={figi}")
        bot.send_message(
            call.message.chat.id,
            f"📌 Вы выбрали акцию с FIGI: **{figi}**\n"
            "🔰 Это пока заглушка — подробная информация появится в следующей версии 😉"
        )
