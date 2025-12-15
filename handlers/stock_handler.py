import telebot
import logging
from typing import List, Dict
from utils.api_client import (
    get_portfolio_positions,
    get_share_info,
    get_last_prices
)

logger = logging.getLogger(__name__)


def format_quotation(quotation: Dict) -> float:
    """
    Форматирует объект Quotation в число.

    Args:
        quotation: Объект с полями units и nano

    Returns:
        float: Значение в виде числа
    """
    if not quotation:
        return 0.0

    # Получаем units и nano
    units = quotation.get("units", 0)
    nano = quotation.get("nano", 0)

    # Преобразуем в числа, если пришли строки
    try:
        units = int(units) if units else 0
    except (ValueError, TypeError):
        units = 0

    try:
        nano = int(nano) if nano else 0
    except (ValueError, TypeError):
        nano = 0

    # Преобразуем nano (наносекунды) в дробную часть
    value = units + (nano / 1_000_000_000)

    return value


def format_money(value: float, currency: str = "RUB") -> str:
    """
    Форматирует сумму денег с символом валюты.

    Args:
        value: Сумма
        currency: Код валюты

    Returns:
        str: Отформатированная строка
    """
    currency_symbols = {
        "RUB": "₽",
        "USD": "$",
        "EUR": "€",
        "rub": "₽",
        "usd": "$",
        "eur": "€"
    }

    symbol = currency_symbols.get(currency, currency)
    return f"{value:,.2f} {symbol}".replace(",", " ")


def create_portfolio_keyboard(positions: List[Dict]) -> telebot.types.InlineKeyboardMarkup:
    """
    Создаёт клавиатуру с акциями из портфеля.

    Args:
        positions: Список позиций из портфеля

    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками
    """
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)

    buttons = []
    for position in positions:
        try:
            # Получаем тикер и количество
            ticker = position.get("ticker", "N/A")
            figi = position.get("figi", ticker)
            quantity = format_quotation(position.get("quantity", {}))

            # Создаём текст кнопки с тикером и количеством
            button_text = f"{ticker} ({int(quantity)} шт.)"

            button = telebot.types.InlineKeyboardButton(
                text=button_text,
                callback_data=f"portfolio_select::{figi}"
            )
            buttons.append(button)
        except Exception as e:
            logger.error(f"Ошибка при создании кнопки для позиции: {e}")
            continue

    # Добавляем кнопки по 2 в ряд
    for i in range(0, len(buttons), 2):
        markup.row(*buttons[i:i + 2])

    return markup


def stock_handler(call, bot):
    """
    Обработчик callback для работы с акциями из портфеля.

    Args:
        call: Callback query от Telegram
        bot: Экземпляр бота
    """

    # Обработка запроса портфеля
    if call.data == "view_stocks":
        logger.info(f"Пользователь {call.from_user.id} запросил свой портфель 📊")

        # Удаляем предыдущее сообщение
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение: {e}")

        # Получаем позиции из портфеля
        positions = get_portfolio_positions()

        if not positions:
            bot.send_message(
                call.message.chat.id,
                "📭 Ваш портфель пуст или не удалось получить данные.\n\n"
                "Возможные причины:\n"
                "• В портфеле нет акций\n"
                "• API временно недоступен\n"
                "• Неверный токен доступа\n"
                "• Токен не имеет прав на чтение портфеля\n\n"
                "💡 Убедитесь, что при создании токена была выбрана "
                "опция 'Только чтение' или полный доступ."
            )
            return

        # Создаём клавиатуру с акциями из портфеля
        markup = create_portfolio_keyboard(positions)

        bot.send_message(
            call.message.chat.id,
            f"💼 Ваш портфель ({len(positions)} позиций) 📈\n"
            "Выберите акцию для просмотра подробной информации:",
            reply_markup=markup
        )

    # Обработка выбора конкретной акции из портфеля
    elif call.data.startswith("portfolio_select::"):
        figi = call.data.split("::")[1]
        logger.info(f"Пользователь {call.from_user.id} выбрал акцию из портфеля FIGI={figi}")

        # Показываем индикатор загрузки
        bot.answer_callback_query(call.id, "⏳ Загружаю данные...")

        # Получаем позиции портфеля для информации о количестве
        positions = get_portfolio_positions()
        position_info = None
        for pos in positions:
            if pos.get("figi") == figi:
                position_info = pos
                break

        if not position_info:
            bot.send_message(
                call.message.chat.id,
                "❌ Не удалось найти эту акцию в портфеле"
            )
            return

        # Получаем детальную информацию об акции
        share_info = get_share_info(figi)

        if not share_info:
            bot.send_message(
                call.message.chat.id,
                f"❌ Не удалось получить информацию об акции с FIGI: `{figi}`",
                parse_mode="Markdown"
            )
            return

        # Получаем последнюю цену
        price_data = get_last_prices([figi])
        current_price = 0.0

        if price_data and "last_prices" in price_data:
            prices = price_data["last_prices"]
            if prices and len(prices) > 0:
                price_obj = prices[0].get("price", {})
                current_price = format_quotation(price_obj)

        # Извлекаем данные из позиции
        ticker = share_info.get("ticker", "N/A")
        name = share_info.get("name", "N/A")
        currency = share_info.get("currency", "RUB")

        # Количество акций
        quantity = format_quotation(position_info.get("quantity", {}))

        # Текущая цена из позиции (может быть более актуальной)
        current_price_pos = format_quotation(position_info.get("currentPrice", {}))

        # Используем наиболее актуальную цену
        if current_price_pos > 0:
            current_price = current_price_pos

        # Средняя цена покупки
        average_price = format_quotation(
            position_info.get("averagePositionPrice", {})
        )

        # Общая стоимость покупки
        total_buy_value = quantity * average_price if average_price > 0 else 0

        # Текущая стоимость
        total_current = quantity * current_price if current_price > 0 else 0

        # Прибыль/убыток
        profit_loss = total_current - total_buy_value if total_buy_value > 0 else 0
        profit_loss_percent = (
            (profit_loss / total_buy_value * 100) if total_buy_value > 0 else 0
        )

        # Определяем emoji для прибыли/убытка
        if profit_loss > 0:
            pl_emoji = "📈 +"
            pl_color = "🟢"
        elif profit_loss < 0:
            pl_emoji = "📉 "
            pl_color = "🔴"
        else:
            pl_emoji = "➡️ "
            pl_color = "⚪"

        # Формируем сообщение с информацией
        message = (
            f"💼 **Позиция в портфеле**\n\n"
            f"🏷️ **Тикер:** `{ticker}`\n"
            f"📝 **Название:** {name}\n"
            f"💰 **Валюта:** {currency}\n\n"
            f"📦 **Количество:** {int(quantity)} шт.\n"
            f"💵 **Средняя цена покупки:** {format_money(average_price, currency)}\n"
            f"💳 **Текущая цена:** {format_money(current_price, currency)}\n\n"
            f"📊 **Стоимость покупки:** {format_money(total_buy_value, currency)}\n"
            f"💎 **Текущая стоимость:** {format_money(total_current, currency)}\n\n"
            f"{pl_color} **Прибыль/Убыток:** {pl_emoji}{format_money(abs(profit_loss), currency)} "
            f"({profit_loss_percent:+.2f}%)\n\n"
            f"🔖 **FIGI:** `{figi}`"
        )

        # Добавляем кнопку возврата к портфелю
        markup = telebot.types.InlineKeyboardMarkup()
        back_button = telebot.types.InlineKeyboardButton(
            "⬅️ К портфелю",
            callback_data="view_stocks"
        )
        markup.add(back_button)

        bot.send_message(
            call.message.chat.id,
            message,
            parse_mode="Markdown",
            reply_markup=markup
        )


def handle_stock_callback(call, bot):
    """
    Обёртка для обработчика с обработкой ошибок.

    Args:
        call: Callback query
        bot: Экземпляр бота
    """
    try:
        stock_handler(call, bot)
    except Exception as e:
        logger.error(f"Ошибка в обработчике акций: {e}", exc_info=True)
        bot.send_message(
            call.message.chat.id,
            "❌ Произошла ошибка при обработке запроса.\n"
            "Попробуйте ещё раз через некоторое время."
        )