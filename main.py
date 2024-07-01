import os
import asyncio
import logging
from alive_progress import alive_bar
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.functions.messages import DeleteHistoryRequest
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.functions.messages import DeleteChatUserRequest
from telethon.tl.types import InputPeerNotifySettings
from telethon.errors import ChatAdminRequiredError
from datetime import datetime, timedelta, timezone
from database import initialize_db, add_account, get_accounts, get_account_by_id

# Инициализация базы данных
asyncio.run(initialize_db())

# Папка для хранения сессий
if not os.path.exists('sessions'):
    os.makedirs('sessions')

# Настройка логгера
logging.basicConfig(filename='tg_cleaner.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

async def add_new_account():
    api_id = input("Введите API ID: ")
    api_hash = input("Введите API Hash: ")
    phone_number = input("Введите номер телефона: ")

    client = TelegramClient(f'sessions/{phone_number}_session', api_id, api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        await client.send_code_request(phone_number)
        try:
            await client.sign_in(phone_number, input('Введите код: '))
        except SessionPasswordNeededError:
            await client.sign_in(password=input('Введите пароль: '))

    user = await client.get_me()
    username = user.username if user.username else str(user.id)
    await add_account(api_id, api_hash, phone_number, username)
    logging.info(f"Аккаунт {username} добавлен.")
    await client.disconnect()

async def list_accounts():
    accounts = await get_accounts()
    print("Доступные аккаунты:")
    for account in accounts:
        print(f"ID: {account[0]}, Username: {account[4]}")
    return accounts

async def select_account():
    accounts = await list_accounts()
    account_id = int(input("Введите ID аккаунта: "))
    account = await get_account_by_id(account_id)
    if account:
        print(f"Выбран аккаунт: {account[4]}")
        return account
    else:
        print("Аккаунт не найден.")
        return None

async def mute_all_channels(account):
    api_id, api_hash, phone_number = account[1], account[2], account[3]
    client = TelegramClient(f'sessions/{phone_number}_session', api_id, api_hash)
    await client.connect()
    await client.start(phone_number)
    logging.info(f"Начинаю заглушение всех каналов для аккаунта {account[4]}")

    async for dialog in client.iter_dialogs():
        if dialog.is_channel:
            try:
                await client(UpdateNotifySettingsRequest(
                    peer=dialog.entity,
                    settings=InputPeerNotifySettings(
                        show_previews=False,
                        silent=True,
                        mute_until=int((datetime.now() + timedelta(weeks=1)).timestamp())
                    )
                ))
                logging.info(f"Канал {dialog.name} заглушен.")
            except FloodWaitError as e:
                logging.warning(f"Flood wait error: необходимо подождать {e.seconds} секунд.")
                await asyncio.sleep(e.seconds)
    print("Все каналы заглушены на 1 неделю.")
    await client.disconnect()

async def delete_inactive_chats(account):
    api_id, api_hash, phone_number = account[1], account[2], account[3]
    inactivity_period = int(input("Введите период неактивности для удаления чатов (в днях): "))
    threshold_date = datetime.now(timezone.utc) - timedelta(days=inactivity_period)

    client = TelegramClient(f'sessions/{phone_number}_session', api_id, api_hash)
    await client.connect()
    await client.start(phone_number)
    logging.info(f"Начинаю удаление неактивных чатов для аккаунта {account[4]}")

    dialogs_count = 0
    async for _ in client.iter_dialogs():
        dialogs_count += 1

    with alive_bar(dialogs_count, title='Удаление неактивных чатов...') as bar:
        async for dialog in client.iter_dialogs():
            if dialog.is_user or dialog.is_group:
                if dialog.id == 777000:
                    bar()
                    continue
                try:
                    last_message = await client.get_messages(dialog.id, limit=1)
                    if last_message:
                        last_message_date = last_message[0].date
                        if last_message_date.replace(tzinfo=timezone.utc) < threshold_date:
                            try:
                                await client(DeleteHistoryRequest(
                                    peer=dialog.entity,
                                    max_id=0,
                                    just_clear=False,
                                    revoke=True
                                ))
                                if hasattr(dialog, 'username') and dialog.username:
                                    logging.info(f"Чат с {dialog.name} удален за неактивность. Ссылка: https://t.me/{dialog.username}")
                                else:
                                    logging.info(f"Чат с {dialog.name} удален за неактивность. ID: {dialog.id}")
                            except ChatAdminRequiredError:
                                logging.warning(f"Недостаточно прав для удаления чата с {dialog.name}")
                except FloodWaitError as e:
                    logging.warning(f"Flood wait error: необходимо подождать {e.seconds} секунд.")
                    await asyncio.sleep(e.seconds)
                bar()
    print("Неактивные чаты удалены.")
    await client.disconnect()

async def leave_inactive_chats_and_channels(account):
    api_id, api_hash, phone_number = account[1], account[2], account[3]
    inactivity_period = int(input("Введите период неактивности для выхода из каналов и чатов (в днях): "))
    threshold_date = datetime.now(timezone.utc) - timedelta(days=inactivity_period)

    client = TelegramClient(f'sessions/{phone_number}_session', api_id, api_hash)
    await client.connect()
    await client.start(phone_number)
    logging.info(f"Начинаю выход из неактивных каналов и чатов для аккаунта {account[4]}")

    dialogs_count = 0
    async for _ in client.iter_dialogs():
        dialogs_count += 1

    with alive_bar(dialogs_count, title='Выход из неактивных каналов и чатов...') as bar:
        async for dialog in client.iter_dialogs():
            if dialog.is_channel or dialog.is_group:
                try:
                    last_message = await client.get_messages(dialog.id, limit=1)
                    if last_message:
                        last_message_date = last_message[0].date
                        if last_message_date.replace(tzinfo=timezone.utc) < threshold_date:
                            try:
                                if dialog.is_channel:
                                    await client(LeaveChannelRequest(
                                        channel=dialog.entity
                                    ))
                                    if hasattr(dialog, 'username') and dialog.username:
                                        logging.info(f"Вышли из канала {dialog.name} за неактивность. Ссылка: https://t.me/{dialog.username}")
                                    else:
                                        logging.info(f"Вышли из канала {dialog.name} за неактивность. ID: {dialog.id}")
                                else:
                                    await client(DeleteChatUserRequest(
                                        chat_id=dialog.entity.id,
                                        user_id='me'
                                    ))
                                    if hasattr(dialog, 'username') and dialog.username:
                                        logging.info(f"Вышли из чата {dialog.name} за неактивность. Ссылка: https://t.me/{dialog.username}")
                                    else:
                                        logging.info(f"Вышли из чата {dialog.name} за неактивность. ID: {dialog.id}")
                            except ChatAdminRequiredError:
                                logging.warning(f"Недостаточно прав для выхода из {dialog.name}")
                except FloodWaitError as e:
                    logging.warning(f"Flood wait error: необходимо подождать {e.seconds} секунд.")
                    await asyncio.sleep(e.seconds)
                bar()
    print("Неактивные чаты и каналы покинуты.")
    await client.disconnect()

async def main():
    selected_account = None
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')  # Очистка консоли
        print("======================================")
        print("        Telegram Account Manager      ")
        print("======================================")
        print("\nГлавное меню:")
        print("1. Добавить новый аккаунт")
        print("2. Выбрать аккаунт")
        print("3. Заглушить все каналы")
        print("4. Удалить неактивные чаты")
        print("5. Выйти из неактивных каналов и чатов")
        print("6. Выйти")
        if selected_account:
            print(f"\nТекущий аккаунт: {selected_account[4]}")
        else:
            print("\nАккаунт не выбран.")
        
        choice = int(input("\nВыберите опцию: "))

        if choice == 1:
            await add_new_account()
        elif choice == 2:
            selected_account = await select_account()
        elif choice == 3:
            if selected_account:
                await mute_all_channels(selected_account)
            else:
                print("Пожалуйста, выберите аккаунт.")
        elif choice == 4:
            if selected_account:
                await delete_inactive_chats(selected_account)
            else:
                print("Пожалуйста, выберите аккаунт.")
        elif choice == 5:
            if selected_account:
                await leave_inactive_chats_and_channels(selected_account)
            else:
                print("Пожалуйста, выберите аккаунт.")
        elif choice == 6:
            break
        else:
            print("Неверный выбор. Пожалуйста, попробуйте снова.")
        input("\nНажмите Enter для продолжения...")

if __name__ == "__main__":
    asyncio.run(main())
