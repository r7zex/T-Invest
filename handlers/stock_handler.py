import telebot
import logging
from typing import List, Dict
from utils.api_client import (
    get_portfolio_positions,
    get_share_info,
    get_last_prices,
    get_withdraw_limits
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
            is_virtual = position.get("is_virtual", False)

            # Создаём текст кнопки с тикером и количеством
            prefix = "🎁 " if is_virtual else ""
            button_text = f"{prefix}{ticker} ({int(quantity)} шт.)"

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
        logger.info(f"📊 Пользователь {call.from_user.id} запросил свой портфель")

        # Удаляем предыдущее сообщение
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            logger.warning(f"⚠️ Не удалось удалить сообщение: {e}")

        # Получаем позиции из портфеля
        positions, portfolio, account_id = get_portfolio_positions()

        logger.info(f"📦 Получено позиций: {len(positions) if positions else 0}")
        logger.info(f"💼 Объект портфеля: {'Да' if portfolio else 'Нет'}")
        logger.info(f"🆔 Account ID: {account_id if account_id else 'Нет'}")

        # Получаем данные по балансам
        limits = None
        if account_id:
            limits = get_withdraw_limits(account_id)
            logger.info(f"💰 Лимиты получены: {'Да' if limits else 'Нет'}")

        def extract_money_value(values):
            if not values:
                return None
            money_item = values[0]
            amount = format_quotation(money_item)
            currency = money_item.get("currency", "RUB")
            return amount, currency

        current_balance = None
        reserved_balance = None

        if limits:
            current_balance = extract_money_value(limits.get("money"))
            reserved_balance = extract_money_value(limits.get("blocked"))
            logger.info(f"💳 Текущий баланс: {current_balance}")
            logger.info(f"⏸️ Зарезервированный: {reserved_balance}")
        elif portfolio:
            current_balance = extract_money_value([portfolio.get("totalAmountCurrencies", {})])
            if current_balance:
                reserved_balance = (0.0, current_balance[1])

        # Если нет позиций И нет баланса - показываем ошибку
        if not positions and not current_balance:
            error_msg = (
                "📭 Ваш портфель пуст или не удалось получить данные.\n\n"
                "Возможные причины:\n"
            )

            if not account_id:
                error_msg += "• ❌ Не удалось получить ID счёта\n"
            if not portfolio:
                error_msg += "• ❌ API не вернул данные портфеля\n"
            if not limits:
                error_msg += "• ❌ Не удалось получить лимиты счёта\n"

            error_msg += (
                "• API временно недоступен\n"
                "• Неверный токен доступа\n"
                "• Токен не имеет прав на чтение портфеля\n\n"
                "💡 Проверьте логи бота для подробной информации.\n"
                "Убедитесь, что при создании токена была выбрана "
                "опция 'Только чтение' или полный доступ."
            )

            bot.send_message(call.message.chat.id, error_msg)
            return

        # Формируем сообщение
        message_lines = []

        if positions:
            message_lines.append(f"💼 Ваш портфель ({len(positions)} позиций) 📈")
        else:
            message_lines.append("💼 Ваш портфель 📊")
            message_lines.append("📭 В портфеле пока нет акций")

        if current_balance:
            amount, currency = current_balance
            message_lines.append(f"💳 Текущий баланс: {format_money(amount, currency)}")

        if reserved_balance:
            amount, currency = reserved_balance
            if amount > 0:
                message_lines.append(f"⏸️ Зарезервировано: {format_money(amount, currency)}")

        if positions:
            message_lines.append("\nВыберите акцию для просмотра подробной информации:")

            # Создаём клавиатуру с акциями из портфеля
            markup = create_portfolio_keyboard(positions)

            bot.send_message(
                call.message.chat.id,
                "\n".join(message_lines),
                reply_markup=markup
            )
        else:
            # Если нет позиций, но есть баланс - просто показываем баланс
            bot.send_message(
                call.message.chat.id,
                "\n".join(message_lines)
            )

    # Обработка выбора конкретной акции из портфеля
    elif call.data.startswith("portfolio_select::"):
        figi = call.data.split("::")[1]
        logger.info(f"Пользователь {call.from_user.id} выбрал акцию из портфеля FIGI={figi}")

        # Показываем индикатор загрузки
        bot.answer_callback_query(call.id, "⏳ Загружаю данные...")

        # Удаляем сообщение с портфелем, чтобы заменить его информацией об акции
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение портфеля: {e}")

        # Получаем позиции портфеля для информации о количестве
        positions, _, _ = get_portfolio_positions()
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

        # Общая стоимость покупки/продажи с учётом возможных отрицательных значений
        total_buy_value = quantity * average_price

        # Текущая стоимость позиции (для шорта будет отрицательной)
        total_current = quantity * current_price

        # Прибыль/убыток учитывает как длинные, так и короткие позиции
        profit_loss = total_current - total_buy_value
        profit_loss_base = abs(total_buy_value)
        profit_loss_percent = (
            (profit_loss / profit_loss_base * 100) if profit_loss_base > 0 else 0
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

        gift_label = "🎁 Подарочная позиция\n" if position_info.get("is_virtual") else ""

        # Формируем сообщение с информацией
        message = (
            f"💼 **Позиция в портфеле**\n\n"
            f"{gift_label}"
            f"🏷️ **Тикер:** `{ticker}`\n"
            f"📝 **Название:** {name}\n"
            f"💰 **Валюта:** {currency}\n\n"
            f"📦 **Количество:** {int(quantity)} шт.\n"
            f"💵 **Средняя цена покупки:** {format_money(average_price, currency)}\n"
            f"💳 **Текущая цена:** {format_money(current_price, currency)}\n\n"
            f"📊 **Стоимость покупки:** {format_money(total_buy_value, currency)}\n"
            f"💎 **Текущая стоимость:** {format_money(total_current, currency)} ({profit_loss_percent:+.2f}%)\n\n"
            f"{pl_color} **Прибыль/Убыток:** {pl_emoji}{format_money(profit_loss, currency)} "
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