import hashlib
import sqlite3
import os

def get_user_db(username):
    return f"{username}_datasets.db"

def initialize_user_database(database):
    conn = sqlite3.connect(database)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            save_path TEXT NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_hash TEXT NOT NULL UNIQUE,
            file_size_mb REAL NOT NULL,
            download_timestamp TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def configure_user(username):
    database = get_user_db(username)
    initialize_user_database(database)
    conn = sqlite3.connect(database)
    cursor = conn.cursor()
    cursor.execute('SELECT save_path, password_hash FROM user_config WHERE id = 1')
    config = cursor.fetchone()
    if config:
        save_path, stored_password_hash = config
    else:
        save_path = input(f"Enter the directory path where {username}'s files should be saved: ")
        # Ensure directory exists
        if not os.path.exists(save_path):
            os.makedirs(save_path)
        password = input(f"Set a password for {username}: ")
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        cursor.execute('INSERT INTO user_config (save_path, password_hash) VALUES (?, ?)', (save_path, password_hash))
        conn.commit()
        stored_password_hash = password_hash
    conn.close()
    return database, save_path, stored_password_hash

def verify_password(stored_password_hash, input_password):
    input_password_hash = hashlib.sha256(input_password.encode()).hexdigest()
    return input_password_hash == stored_password_hash
