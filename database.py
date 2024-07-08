import aiosqlite

async def initialize_db():
    async with aiosqlite.connect('accounts.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY,
                api_id TEXT NOT NULL,
                api_hash TEXT NOT NULL,
                phone_number TEXT NOT NULL,
                username TEXT,
                proxy TEXT
            )
        ''')
        await db.commit()

async def add_account(api_id, api_hash, phone_number, username):
    async with aiosqlite.connect('accounts.db') as db:
        await db.execute('''
            INSERT INTO accounts (api_id, api_hash, phone_number, username)
            VALUES (?, ?, ?, ?)
        ''', (api_id, api_hash, phone_number, username))
        await db.commit()

async def get_accounts():
    async with aiosqlite.connect('accounts.db') as db:
        async with db.execute('SELECT * FROM accounts') as cursor:
            accounts = await cursor.fetchall()
            return accounts

async def get_account_by_id(account_id):
    async with aiosqlite.connect('accounts.db') as db:
        async with db.execute('SELECT * FROM accounts WHERE id = ?', (account_id,)) as cursor:
            account = await cursor.fetchone()
            return account

async def update_account_proxy(account_id, proxy):
    proxy_str = None
    if proxy:
        proxy_str = ','.join(map(str, proxy))
    async with aiosqlite.connect('accounts.db') as db:
        await db.execute('''
            UPDATE accounts
            SET proxy = ?
            WHERE id = ?
        ''', (proxy_str, account_id))
        await db.commit()
