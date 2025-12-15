from bot import bot  # Импортируем объект bot из bot.py

# Запуск бота
if __name__ == '__main__':
    print("Бот запускается...")  # Это вывод в консоль
    bot.polling(none_stop=True)
