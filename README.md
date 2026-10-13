# BET Coupon Agent

Агент мониторит Telegram Web с 12:00 до 22:00 по времени `Asia/Almaty`, ищет посты,
начинающиеся с `БЕСПЛАТНЫЙ ПРОГНОЗ НА МАТЧ`, распознаёт купон локальной
моделью Ollama, собирает такой же купон в Olimpbet и отправляет результат в Telegram.

## Граница безопасности

Агент только собирает купон. В коде нет метода, нажимающего кнопку подтверждения ставки.
Сумма со скриншота не копируется.

## Установка

```powershell
cd C:\Users\AA\Downloads\Business\BET
py -m pip install -e ".[dev]"
py -m playwright install chromium
Copy-Item .env.example .env.local
```

Данные в `password.txt` или `.env.local` задаются в формате `KEY=VALUE`:

```text
OLIMP_LOGIN=
OLIMP_PASSWORD=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Для `password.txt` также поддерживается сокращённый формат: логин на первой строке и пароль на второй.

Оба файла игнорируются Git. Значения не печатаются в лог.

## Первичный вход

```powershell
bet-agent setup
```

Для Telegram Web нужна сохранённая сессия в `.state/telegram`.
Для добавления исхода в купон Olimpbet требует вход. Агент заполняет форму из `password.txt`,
но не подтверждает ставку и не указывает сумму.

## Запуск

```powershell
bet-agent once
bet-agent run
```

Пока Telegram-бот не настроен, уведомления печатаются в консоль. После создания бота
добавьте `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`.
