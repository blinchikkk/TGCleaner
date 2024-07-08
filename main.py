import os
import asyncio
import logging
from alive_progress import alive_bar
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError, ChatAdminRequiredError
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.functions.messages import DeleteHistoryRequest
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.functions.messages import DeleteChatUserRequest
from telethon.tl.types import InputPeerNotifySettings
from datetime import datetime, timedelta, timezone
from database import initialize_db, add_account, get_accounts, get_account_by_id, update_account_proxy

# Инициализация базы данных
asyncio.run(initialize_db())

# Папка для хранения сессий
if not os.path.exists('sessions'):
    os.makedirs('sessions')

# Настройка логгера
logging.basicConfig(filename='tg_cleaner.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

class TelegramAccountManager:
    def __init__(self):
        self.selected_account = None

    async def add_new_account(self):
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

    async def list_accounts(self):
        accounts = await get_accounts()
        print("Доступные аккаунты:")
        for account in accounts:
            print(f"ID: {account[0]}, Username: {account[4]}")
        return accounts

    async def select_account(self):
        accounts = await self.list_accounts()
        account_id = int(input("Введите ID аккаунта: "))
        account = await get_account_by_id(account_id)
        if account:
            print(f"Выбран аккаунт: {account[4]}")
            self.selected_account = account
        else:
            print("Аккаунт не найден.")
            self.selected_account = None

    async def set_proxy(self):
        if not self.selected_account:
            print("Пожалуйста, выберите аккаунт.")
            return

        use_proxy = input("Использовать прокси? (да/нет): ").lower() == 'да'
        proxy = None
        if use_proxy:
            proxy_type = input("Тип прокси (socks5/socks4/http): ").lower()
            proxy_addr = input("Адрес прокси: ")
            proxy_port = int(input("Порт прокси: "))
            proxy = (proxy_type, proxy_addr, proxy_port)
            if proxy_type == 'socks5':
                proxy_username = input("Прокси логин (если нет, оставить пустым): ")
                proxy_password = input("Прокси пароль (если нет, оставить пустым): ")
                if proxy_username and proxy_password:
                    proxy = (proxy_type, proxy_addr, proxy_port, True, proxy_username, proxy_password)

        await update_account_proxy(self.selected_account[0], proxy)
        print("Настройки прокси обновлены.")
        logging.info(f"Прокси обновлен для аккаунта {self.selected_account[4]}")

    async def get_client(self):
        api_id, api_hash, phone_number, proxy = self.selected_account[1], self.selected_account[2], self.selected_account[3], self.selected_account[5]
        return TelegramClient(f'sessions/{phone_number}_session', api_id, api_hash, proxy=proxy)

    async def mute_all_channels(self, mute_duration):
        if not self.selected_account:
            print("Пожалуйста, выберите аккаунт.")
            return

        client = await self.get_client()
        await client.connect()
        await client.start(phone_number=self.selected_account[3])
        logging.info(f"Начинаю заглушение всех каналов для аккаунта {self.selected_account[4]}")

        dialogs_count = 0
        async for dialog in client.iter_dialogs():
            if dialog.is_channel:
                dialogs_count += 1

        with alive_bar(dialogs_count, title='Заглушение всех каналов...') as bar:
            async for dialog in client.iter_dialogs():
                if dialog.is_channel:
                    while True:
                        try:
                            mute_until = 0 if mute_duration == 0 else int((datetime.now() + timedelta(minutes=mute_duration)).timestamp())
                            await client(UpdateNotifySettingsRequest(
                                peer=dialog.entity,
                                settings=InputPeerNotifySettings(
                                    show_previews=False,
                                    silent=True,
                                    mute_until=mute_until
                                )
                            ))
                            logging.info(f"Канал {dialog.name} заглушен.")
                            break
                        except FloodWaitError as e:
                            logging.warning(f"Flood wait error: необходимо подождать {e.seconds} секунд.")
                            await asyncio.sleep(e.seconds)
                    bar()
        print("Все каналы заглушены.")
        await client.disconnect()

    async def delete_inactive_chats(self, inactivity_period):
        if not self.selected_account:
            print("Пожалуйста, выберите аккаунт.")
            return

        client = await self.get_client()
        await client.connect()
        await client.start(phone_number=self.selected_account[3])
        logging.info(f"Начинаю удаление неактивных чатов для аккаунта {self.selected_account[4]}")

        dialogs_count = 0
        async for dialog in client.iter_dialogs():
            if dialog.is_user or dialog.is_group:
                dialogs_count += 1

        with alive_bar(dialogs_count, title='Удаление неактивных чатов...') as bar:
            async for dialog in client.iter_dialogs():
                if dialog.is_user or dialog.is_group:
                    if dialog.id == 777000:
                        bar()
                        continue
                    while True:
                        try:
                            last_message = await client.get_messages(dialog.id, limit=1)
                            if last_message:
                                last_message_date = last_message[0].date
                                if last_message_date.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc) - timedelta(days=inactivity_period):
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
                            break
                        except FloodWaitError as e:
                            logging.warning(f"Flood wait error: необходимо подождать {e.seconds} секунд.")
                            await asyncio.sleep(e.seconds)
                    bar()
        print("Неактивные чаты удалены.")
        await client.disconnect()

    async def leave_inactive_chats_and_channels(self, inactivity_period):
        if not self.selected_account:
            print("Пожалуйста, выберите аккаунт.")
            return

        client = await self.get_client()
        await client.connect()
        await client.start(phone_number=self.selected_account[3])
        logging.info(f"Начинаю выход из неактивных каналов и чатов для аккаунта {self.selected_account[4]}")

        dialogs_count = 0
        async for _ in client.iter_dialogs():
            dialogs_count += 1

        with alive_bar(dialogs_count, title='Выход из неактивных каналов и чатов...') as bar:
            async for dialog in client.iter_dialogs():
                if dialog.is_channel or dialog.is_group:
                    while True:
                        try:
                            last_message = await client.get_messages(dialog.id, limit=1)
                            if last_message:
                                last_message_date = last_message[0].date
                                if last_message_date.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc) - timedelta(days=inactivity_period):
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
                            break
                        except FloodWaitError as e:
                            logging.warning(f"Flood wait error: необходимо подождать {e.seconds} секунд.")
                            await asyncio.sleep(e.seconds)
                    bar()
        print("Неактивные чаты и каналы покинуты.")
        await client.disconnect()

    async def main_menu(self):
        while True:
            os.system('cls' if os.name == 'nt' else 'clear')  # Очистка консоли
            print("======================================")
            print("        Telegram Account Manager      ")
            print("======================================")
            print("\nГлавное меню:")
            print("1. Добавить новый аккаунт")
            print("2. Выбрать аккаунт")
            print("3. Установить прокси")
            print("4. Заглушить все каналы")
            print("5. Удалить неактивные чаты")
            print("6. Выйти из неактивных каналов и чатов")
            print("7. Выйти")
            if self.selected_account:
                print(f"\nТекущий аккаунт: {self.selected_account[4]}")
            else:
                print("\nАккаунт не выбран.")
            
            choice = int(input("\nВыберите опцию: "))

            if choice == 1:
                await self.add_new_account()
            elif choice == 2:
                await self.select_account()
            elif choice == 3:
                await self.set_proxy()
            elif choice == 4:
                mute_duration = int(input("Введите время в минутах (0 - навсегда): "))
                await self.mute_all_channels(mute_duration)
            elif choice == 5:
                inactivity_period = int(input("Введите период неактивности для удаления чатов (в днях): "))
                await self.delete_inactive_chats(inactivity_period)
            elif choice == 6:
                inactivity_period = int(input("Введите период неактивности для выхода из каналов и чатов (в днях): "))
                await self.leave_inactive_chats_and_channels(inactivity_period)
            elif choice == 7:
                break
            else:
                print("Неверный выбор. Пожалуйста, попробуйте снова.")
            input("\nНажмите Enter для продолжения...")

if __name__ == "__main__":
    manager = TelegramAccountManager()
    asyncio.run(manager.main_menu())
