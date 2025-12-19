import telebot
import logging
from typing import List, Dict, Tuple
from datetime import datetime, timedelta
from utils.api_client import (
    get_portfolio_positions,
    get_share_info,
    get_last_prices,
    get_withdraw_limits,
    format_quotation,
    get_candles,
    get_portfolio_history,
    get_portfolio_value_yesterday
)
from utils.chart_generator import generate_balance_chart, generate_stock_chart, format_price_with_precision

logger = logging.getLogger(__name__)


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


def format_quantity_display(quantity: float, is_virtual: bool) -> str:
    """
    Форматирует количество акций для отображения.

    Для подарочных (виртуальных) акций с дробной частью показывает
    дробное число (например, "5.50"), для остальных случаев - целое ("5").

    Args:
        quantity: Количество акций
        is_virtual: Флаг подарочной позиции

    Returns:
        str: Отформатированное количество
    """
    if isinstance(quantity, (int, float)) and is_virtual and quantity != int(quantity):
        return f"{quantity:.2f}"
    elif isinstance(quantity, (int, float)):
        return str(int(quantity))
    else:
        return "N/A"


def calculate_position_growth(position: Dict, current_price: float) -> Tuple[float, float]:
    """
    Рассчитывает абсолютный и относительный рост позиции.

    Args:
        position: Позиция из портфеля
        current_price: Текущая цена акции

    Returns:
        Tuple[float, float]: (абсолютный рост, относительный рост в %)
    """
    quantity = format_quotation(position.get("quantity", {}))
    average_price = format_quotation(position.get("averagePositionPrice", {}))

    current_value = quantity * current_price
    buy_value = quantity * average_price

    absolute_growth = current_value - buy_value
    relative_growth = (absolute_growth / buy_value * 100) if buy_value != 0 else 0

    return absolute_growth, relative_growth


def create_portfolio_keyboard(
        positions: List[Dict],
        prices_data: Dict = None
) -> telebot.types.InlineKeyboardMarkup:
    """
    Создаёт клавиатуру с акциями из портфеля.

    Args:
        positions: Список позиций из портфеля
        prices_data: Данные о текущих ценах акций

    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками
    """
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)

    # Добавляем кнопку для динамики баланса
    dynamics_button = telebot.types.InlineKeyboardButton(
        "📈 К динамике баланса",
        callback_data="balance_dynamics::1w"
    )
    markup.add(dynamics_button)

    # Получаем цены
    price_map = {}
    if prices_data and "last_prices" in prices_data:
        for price_item in prices_data["last_prices"]:
            figi = price_item.get("figi")
            price = format_quotation(price_item.get("price", {}))
            price_map[figi] = price

    buttons = []
    for position in positions:
        try:
            # Получаем тикер
            ticker = position.get("ticker", "N/A")
            figi = position.get("figi", ticker)
            quantity = format_quotation(position.get("quantity", {}))
            is_virtual = position.get("is_virtual", False)

            # Получаем текущую цену
            current_price = price_map.get(figi, 0)
            if current_price == 0:
                current_price = format_quotation(position.get("currentPrice", {}))

            # Создаём текст кнопки с тикером и ростом (БЕЗ количества)
            prefix = "🎁 " if is_virtual else ""

            # Рассчитываем рост/падение
            if current_price > 0:
                absolute_growth, relative_growth = calculate_position_growth(position, current_price)

                # Форматируем знак и эмодзи
                if absolute_growth >= 0:
                    emoji = "🟢"
                    sign = "+"
                else:
                    emoji = "🔴"
                    sign = ""

                currency = position.get("currency", "RUB")
                currency_symbol = "₽" if currency == "RUB" else currency

                button_text = (
                    f"{emoji} {prefix}{ticker} "
                    f"{sign}{relative_growth:.1f}% "
                    f"{sign}{absolute_growth:.0f}{currency_symbol}"
                )
            else:
                button_text = f"{prefix}{ticker}"

            button = telebot.types.InlineKeyboardButton(
                text=button_text,
                callback_data=f"portfolio_select::{figi}"
            )
            buttons.append(button)
        except Exception as e:
            logger.error(f"Ошибка при создании кнопки для позиции: {e}")
            continue

    # Добавляем кнопки с акциями по 2 в ряд
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
        positions, portfolio, account_id = get_portfolio_positions()

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

        # Получаем данные по балансам
        limits = get_withdraw_limits(account_id) if account_id else None

        def extract_money_value(values):
            if not values:
                return None
            money_item = values[0]
            amount = format_quotation(money_item)
            currency = money_item.get("currency", "RUB")
            return amount, currency

        current_balance = None

        if limits:
            current_balance = extract_money_value(limits.get("money"))
        elif portfolio:
            current_balance = extract_money_value([portfolio.get("totalAmountCurrencies", {})])

        # Получаем текущие цены для всех позиций
        figis = [pos.get("figi") for pos in positions if pos.get("figi")]
        prices_data = get_last_prices(figis) if figis else None

        # Рассчитываем сумму по всем акциям и прибыль
        stocks_value = 0.0
        total_buy_value = 0.0
        currency = "RUB"

        price_map = {}
        if prices_data and "last_prices" in prices_data:
            for price_item in prices_data["last_prices"]:
                figi = price_item.get("figi")
                price = format_quotation(price_item.get("price", {}))
                price_map[figi] = price

        for position in positions:
            figi = position.get("figi")
            quantity = format_quotation(position.get("quantity", {}))
            average_price = format_quotation(position.get("averagePositionPrice", {}))
            currency = position.get("currency", "RUB")

            current_price = price_map.get(figi, 0)
            if current_price == 0:
                current_price = format_quotation(position.get("currentPrice", {}))

            stocks_value += quantity * current_price
            total_buy_value += quantity * average_price

        # Стоимость портфеля = текущий баланс + сумма по всем акциям
        balance_amount = current_balance[0] if current_balance else 0.0
        portfolio_value = balance_amount + stocks_value

        # Прибыль за всё время (абсолютная)
        total_profit_absolute = stocks_value - total_buy_value

        # Относительная прибыль = x / (стоимость портфеля - x)
        portfolio_value_without_profit = portfolio_value - total_profit_absolute
        total_profit_percent = (
                    total_profit_absolute / portfolio_value_without_profit * 100) if portfolio_value_without_profit != 0 else 0

        # Прибыль за сегодня
        yesterday_value = get_portfolio_value_yesterday(account_id) if account_id else None

        if yesterday_value is not None and yesterday_value > 0:
            today_profit_absolute = portfolio_value - yesterday_value

            # Относительная прибыль за сегодня = x / (стоимость портфеля - x)
            portfolio_value_without_today_profit = portfolio_value - today_profit_absolute
            today_profit_percent = (
                        today_profit_absolute / portfolio_value_without_today_profit * 100) if portfolio_value_without_today_profit != 0 else 0
        else:
            today_profit_absolute = 0.0
            today_profit_percent = 0.0
            logger.warning("Не удалось рассчитать изменение за сегодня - используем нулевые значения")

        # Создаём клавиатуру с акциями из портфеля
        markup = create_portfolio_keyboard(positions, prices_data)

        message_lines = [f"💼 Ваш портфель ({len(positions)} позиций) 📈\n"]

        if current_balance:
            amount, curr = current_balance
            message_lines.append(f"💳 Текущий баланс: {format_money(amount, curr)}")

        message_lines.append(f"💎 Стоимость портфеля: {format_money(portfolio_value, currency)}")

        # Прибыль за всё время
        profit_sign = "+" if total_profit_absolute >= 0 else ""
        profit_emoji = "🟢" if total_profit_absolute >= 0 else "🔴"
        message_lines.append(
            f"{profit_emoji} Прибыль за всё время: {profit_sign}{format_money(total_profit_absolute, currency)} "
            f"({profit_sign}{total_profit_percent:.2f}%)"
        )

        # Изменение за сегодня
        today_sign = "+" if today_profit_absolute >= 0 else ""
        today_emoji = "🟢" if today_profit_absolute >= 0 else "🔴"
        message_lines.append(
            f"{today_emoji} Изменение за сегодня: {today_sign}{format_money(today_profit_absolute, currency)} "
            f"({today_sign}{today_profit_percent:.2f}%)"
        )

        message_lines.append("\nВыберите акцию для просмотра:")

        bot.send_message(
            call.message.chat.id,
            "\n".join(message_lines),
            reply_markup=markup
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

        # Получаем позиции портфеля из кэша (использует кэш если доступен)
        positions, _, _ = get_portfolio_positions(use_cache=True)
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

        is_virtual = position_info.get("is_virtual", False)
        gift_label = "🎁 Подарочная позиция\n" if is_virtual else ""

        # Форматируем количество с помощью вспомогательной функции
        qty_display = format_quantity_display(quantity, is_virtual)

        # Формируем сообщение с информацией
        message = (
            f"💼 **Позиция в портфеле**\n\n"
            f"{gift_label}"
            f"🏷️ **Тикер:** `{ticker}`\n"
            f"📝 **Название:** {name}\n"
            f"💰 **Валюта:** {currency}\n\n"
            f"📦 **Количество:** {qty_display} шт.\n"
            f"💵 **Средняя цена покупки:** {format_money(average_price, currency)}\n"
            f"💳 **Текущая цена:** {format_money(current_price, currency)}\n\n"
            f"📊 **Стоимость покупки:** {format_money(total_buy_value, currency)}\n"
            f"💎 **Текущая стоимость:** {format_money(total_current, currency)} ({profit_loss_percent:+.2f}%)\n\n"
            f"{pl_color} **Прибыль/Убыток:** {pl_emoji}{format_money(profit_loss, currency)} "
            f"({profit_loss_percent:+.2f}%)\n\n"
            f"🔖 **FIGI:** `{figi}`"
        )

        # Добавляем кнопки навигации
        markup = telebot.types.InlineKeyboardMarkup()
        dynamics_button = telebot.types.InlineKeyboardButton(
            "📈 Динамика акции",
            callback_data=f"stock_dynamics::{figi}::1w"
        )
        back_button = telebot.types.InlineKeyboardButton(
            "⬅️ К портфелю",
            callback_data="view_stocks"
        )
        markup.add(dynamics_button)
        markup.add(back_button)

        bot.send_message(
            call.message.chat.id,
            message,
            parse_mode="Markdown",
            reply_markup=markup
        )

    # Обработка просмотра динамики баланса
    elif call.data.startswith("balance_dynamics::"):
        period = call.data.split("::")[1]
        logger.info(f"Пользователь {call.from_user.id} запросил динамику баланса за период {period}")

        # Показываем индикатор загрузки
        bot.answer_callback_query(call.id, "⏳ Загружаю данные...")

        # Удаляем предыдущее сообщение
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение: {e}")

        # Определяем временной интервал
        now = datetime.utcnow()
        period_map = {
            "1h": (now - timedelta(hours=1), "CANDLE_INTERVAL_1_MIN"),
            "1d": (now - timedelta(days=1), "CANDLE_INTERVAL_HOUR"),
            "1w": (now - timedelta(weeks=1), "CANDLE_INTERVAL_HOUR"),
            "1m": (now - timedelta(days=30), "CANDLE_INTERVAL_DAY"),
            "1y": (now - timedelta(days=365), "CANDLE_INTERVAL_DAY")
        }

        from_date, interval = period_map.get(period, (now - timedelta(weeks=1), "CANDLE_INTERVAL_HOUR"))
        from_date_str = from_date.isoformat() + "Z"
        to_date_str = now.isoformat() + "Z"

        # Получаем историю портфеля
        positions, portfolio, account_id = get_portfolio_positions(use_cache=False)
        history = get_portfolio_history(account_id, from_date_str, to_date_str) if account_id else None

        if history and len(history) > 0:
            # Генерируем график
            chart_bytes = generate_balance_chart(history, period)

            # Создаём клавиатуру с выбором периода
            markup = telebot.types.InlineKeyboardMarkup(row_width=2)

            # Кнопки периодов (исключая текущий)
            period_buttons = []
            periods = [("1ч", "1h"), ("1д", "1d"), ("1Н", "1w"), ("1М", "1m"), ("1Г", "1y")]
            for label, p in periods:
                if p != period:
                    period_buttons.append(
                        telebot.types.InlineKeyboardButton(label, callback_data=f"balance_dynamics::{p}")
                    )

            # Добавляем кнопки периодов по 2 в ряд
            for i in range(0, len(period_buttons), 2):
                markup.row(*period_buttons[i:i + 2])

            # Кнопка назад к портфелю
            portfolio_btn = telebot.types.InlineKeyboardButton(
                "💼 К портфелю",
                callback_data="view_stocks"
            )
            markup.add(portfolio_btn)

            # Отправляем график
            bot.send_photo(
                call.message.chat.id,
                chart_bytes,
                caption=f"📈 Динамика баланса за период: {dict(map(lambda x: x[::-1], periods))[period]}",
                reply_markup=markup
            )
        else:
            # Добавляем кнопку "Назад" при недостаточном количестве данных
            markup = telebot.types.InlineKeyboardMarkup()
            back_button = telebot.types.InlineKeyboardButton(
                "⬅️ Назад к графику за 7 дней",
                callback_data="balance_dynamics::1w"
            )
            markup.add(back_button)

            bot.send_message(
                call.message.chat.id,
                "❌ Не удалось получить историю баланса портфеля.\n\n"
                "Возможно, недостаточно данных для построения графика за выбранный период.",
                reply_markup=markup
            )

    # Обработка просмотра динамики акции
    elif call.data.startswith("stock_dynamics::"):
        parts = call.data.split("::")
        figi = parts[1]
        period = parts[2] if len(parts) > 2 else "1w"

        logger.info(f"Пользователь {call.from_user.id} запросил динамику акции {figi} за период {period}")

        # Показываем индикатор загрузки
        bot.answer_callback_query(call.id, "⏳ Загружаю данные...")

        # Удаляем предыдущее сообщение
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщение: {e}")

        # Получаем информацию об акции
        share_info = get_share_info(figi)
        ticker = share_info.get("ticker", "N/A") if share_info else "N/A"
        stock_name = share_info.get("name", ticker) if share_info else ticker
        currency = share_info.get("currency", "RUB") if share_info else "RUB"

        # Определяем временной интервал
        now = datetime.utcnow()
        period_map = {
            "1h": (now - timedelta(hours=1), "CANDLE_INTERVAL_1_MIN"),
            "1d": (now - timedelta(days=1), "CANDLE_INTERVAL_HOUR"),
            "1w": (now - timedelta(weeks=1), "CANDLE_INTERVAL_HOUR"),
            "1m": (now - timedelta(days=30), "CANDLE_INTERVAL_DAY"),
            "1y": (now - timedelta(days=365), "CANDLE_INTERVAL_DAY")
        }

        from_date, interval = period_map.get(period, (now - timedelta(weeks=1), "CANDLE_INTERVAL_HOUR"))
        from_date_str = from_date.isoformat() + "Z"
        to_date_str = now.isoformat() + "Z"

        # Получаем исторические свечи
        candles = get_candles(figi, from_date_str, to_date_str, interval)

        if candles and len(candles) > 0:
            # Преобразуем свечи в формат для графика
            history = []
            for candle in candles:
                timestamp_str = candle.get("time")
                close_price = format_quotation(candle.get("close", {}))

                if timestamp_str and close_price > 0:
                    try:
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        history.append({
                            'timestamp': timestamp,
                            'price': close_price
                        })
                    except Exception as e:
                        logger.warning(f"Не удалось преобразовать timestamp {timestamp_str}: {e}")
                        continue

            if history:
                # Генерируем график
                chart_bytes = generate_stock_chart(figi, history, period, stock_name, currency)

                # Создаём клавиатуру с выбором периода
                markup = telebot.types.InlineKeyboardMarkup(row_width=2)

                # Кнопки периодов (исключая текущий)
                period_buttons = []
                periods = [("1ч", "1h"), ("1д", "1d"), ("1Н", "1w"), ("1М", "1m"), ("1Г", "1y")]
                for label, p in periods:
                    if p != period:
                        period_buttons.append(
                            telebot.types.InlineKeyboardButton(
                                label,
                                callback_data=f"stock_dynamics::{figi}::{p}"
                            )
                        )

                # Добавляем кнопки периодов по 2 в ряд
                for i in range(0, len(period_buttons), 2):
                    markup.row(*period_buttons[i:i + 2])

                # Кнопки навигации
                stock_info_btn = telebot.types.InlineKeyboardButton(
                    "📊 К акции",
                    callback_data=f"portfolio_select::{figi}"
                )
                portfolio_btn = telebot.types.InlineKeyboardButton(
                    "💼 К портфелю",
                    callback_data="view_stocks"
                )
                markup.add(stock_info_btn)
                markup.add(portfolio_btn)

                # Отправляем график
                bot.send_photo(
                    call.message.chat.id,
                    chart_bytes,
                    caption=f"📈 Динамика цены {stock_name} за период: {period}",
                    reply_markup=markup
                )
            else:
                # Добавляем кнопку "Назад" при недостаточном количестве данных
                markup = telebot.types.InlineKeyboardMarkup()
                back_button = telebot.types.InlineKeyboardButton(
                    "⬅️ Назад к графику за 7 дней",
                    callback_data=f"stock_dynamics::{figi}::1w"
                )
                stock_info_btn = telebot.types.InlineKeyboardButton(
                    "📊 К акции",
                    callback_data=f"portfolio_select::{figi}"
                )
                markup.add(back_button)
                markup.add(stock_info_btn)

                bot.send_message(
                    call.message.chat.id,
                    f"❌ Не удалось построить график для {stock_name}.\n\n"
                    "Данные о ценах недоступны для выбранного периода.",
                    reply_markup=markup
                )
        else:
            # Добавляем кнопку "Назад" при недостаточном количестве данных
            markup = telebot.types.InlineKeyboardMarkup()
            back_button = telebot.types.InlineKeyboardButton(
                "⬅️ Назад к графику за 7 дней",
                callback_data=f"stock_dynamics::{figi}::1w"
            )
            stock_info_btn = telebot.types.InlineKeyboardButton(
                "📊 К акции",
                callback_data=f"portfolio_select::{figi}"
            )
            markup.add(back_button)
            markup.add(stock_info_btn)

            bot.send_message(
                call.message.chat.id,
                f"❌ Не удалось получить историю цен для {stock_name}.\n\n"
                "Возможно, недостаточно данных для построения графика за выбранный период.",
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