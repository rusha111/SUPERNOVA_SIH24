import hashlib
import sqlite3
import os
import shutil
import tempfile
import requests
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

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
        save_path = '/path/to/default'
        if not os.path.exists(save_path):
            os.makedirs(save_path)
        password = request.form['password']
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        cursor.execute('INSERT INTO user_config (save_path, password_hash) VALUES (?, ?)', (save_path, password_hash))
        conn.commit()
        stored_password_hash = password_hash
    conn.close()
    return database, save_path, stored_password_hash

def verify_password(stored_password_hash, input_password):
    input_password_hash = hashlib.sha256(input_password.encode()).hexdigest()
    return input_password_hash == stored_password_hash

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('download'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    database, _, stored_password_hash = configure_user(username)
    if verify_password(stored_password_hash, password):
        session['username'] = username
        return redirect(url_for('download'))
    else:
        flash('Invalid credentials')
        return redirect(url_for('index'))

@app.route('/signup')
def signup():
    return render_template('signup.html')

@app.route('/signup', methods=['POST'])
def signup_user():
    username = request.form['username']
    password = request.form['password']
    save_path = request.form['save_path']
    if not os.path.exists(save_path):
        os.makedirs(save_path)
    database = get_user_db(username)
    initialize_user_database(database)
    conn = sqlite3.connect(database)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO user_config (save_path, password_hash) VALUES (?, ?)', 
                   (save_path, hashlib.sha256(password.encode()).hexdigest()))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/download', methods=['GET', 'POST'])
def download():
    if 'username' not in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        file_url = request.form['file_url']
        database = get_user_db(session['username'])
        conn = sqlite3.connect(database)
        cursor = conn.cursor()
        cursor.execute('SELECT save_path FROM user_config WHERE id = 1')
        save_path = cursor.fetchone()[0]
        conn.close()

        try:
            response = requests.get(file_url, stream=True)
            response.raise_for_status()

            # Use a context manager for temporary file
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)
                temp_file_path = temp_file.name

            # Calculate file hash
            file_hash = hashlib.sha256()
            with open(temp_file_path, 'rb') as f:
                while chunk := f.read(8192):
                    file_hash.update(chunk)
            file_hash = file_hash.hexdigest()

            # Get file size in MB
            file_size_mb = os.path.getsize(temp_file_path) / (1024 * 1024)
            download_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Check for existing file and handle accordingly
            conn = sqlite3.connect(database)
            cursor = conn.cursor()
            cursor.execute('SELECT file_name, file_path FROM datasets WHERE file_hash = ?', (file_hash,))
            existing_data = cursor.fetchone()
            if existing_data:
                flash(f"File already exists: Name: {existing_data[0]}, Path: {existing_data[1]}")
            else:
                file_name = request.form['file_name']
                dest_path = os.path.join(save_path, file_name)
                shutil.copy(temp_file_path, dest_path)
                conn = sqlite3.connect(database)
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO datasets (file_name, file_path, file_hash, file_size_mb, download_timestamp)
                    VALUES (?, ?, ?, ?, ?)
                ''', (file_name, dest_path, file_hash, file_size_mb, download_timestamp))
                conn.commit()
                conn.close()
                flash(f"File '{file_name}' downloaded successfully and details stored.")
            os.remove(temp_file_path)
        except requests.exceptions.RequestException as e:
            flash(f"Failed to download file: {e}")

    return render_template('download.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('index'))

if __name__ == "__main__":
    app.run(debug=True)
