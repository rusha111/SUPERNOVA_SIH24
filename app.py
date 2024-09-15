from datetime import datetime
import hashlib
import sqlite3
import os
import shutil
import tempfile
import requests
import time  # Add this import at the top of your file

from flask import Flask, render_template, request, redirect, url_for, session, flash
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
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
        file_name = request.form['file_name']
        database = get_user_db(session['username'])
        conn = sqlite3.connect(database)
        cursor = conn.cursor()
        cursor.execute('SELECT save_path FROM user_config WHERE id = 1')
        save_path = cursor.fetchone()[0]
        conn.close()

        temp_download_path = tempfile.mkdtemp()  # Create a temporary directory

        try:
            # Set up Selenium
            chrome_options = Options()
            chrome_options.add_argument("--start-maximized")  # Open the browser in maximized mode

            # Set download directory
            chrome_options.add_experimental_option('prefs', {
                'download.default_directory': temp_download_path,
                'download.prompt_for_download': False,
                'download.directory_upgrade': True,
                'safebrowsing.enabled': True
            })

            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.get(file_url)

            # Polling loop to check for download completion
            timeout = 60  # Timeout in seconds
            start_time = datetime.now()
            downloaded_file_path = None

            while (datetime.now() - start_time).total_seconds() < timeout:
                downloaded_files = os.listdir(temp_download_path)
                for filename in downloaded_files:
                    temp_file_path = os.path.join(temp_download_path, filename)
                    if os.path.isfile(temp_file_path):
                        # Check if the file is still being written
                        if is_file_complete(temp_file_path):
                            downloaded_file_path = temp_file_path
                            break
                if downloaded_file_path:
                    break
                time.sleep(1)  # Sleep for 1 second before checking again

            if downloaded_file_path:
                # Calculate file hash and size
                file_hash = hashlib.sha256()
                with open(downloaded_file_path, 'rb') as f:
                    while chunk := f.read(8192):
                        file_hash.update(chunk)
                file_hash = file_hash.hexdigest()

                file_size_mb = os.path.getsize(downloaded_file_path) / (1024 * 1024)
                download_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                conn = sqlite3.connect(database)
                cursor = conn.cursor()
                cursor.execute('SELECT file_name, file_path, file_size_mb, download_timestamp FROM datasets WHERE file_hash = ?', (file_hash,))
                existing_data = cursor.fetchone()
                conn.close()

                if existing_data:
                    return render_template('file_exists.html', 
                                           file_name=existing_data[0], 
                                           file_path=existing_data[1], 
                                           file_size_mb=existing_data[2], 
                                           download_timestamp=existing_data[3], 
                                           file_url=file_url, 
                                           requested_file_name=file_name)
                else:
                    dest_path = os.path.join(save_path, file_name)
                    shutil.copy(downloaded_file_path, dest_path)  # Copy file to permanent location
                    conn = sqlite3.connect(database)
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO datasets (file_name, file_path, file_hash, file_size_mb, download_timestamp)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (file_name, dest_path, file_hash, file_size_mb, download_timestamp))
                    conn.commit()
                    conn.close()
                    flash(f"File '{file_name}' downloaded successfully and details stored.")
            else:
                flash("No files found in the temporary download directory.")
        except Exception as e:
            flash(f"An error occurred: {e}")
        finally:
            driver.quit()
            # Clean up temporary files
            shutil.rmtree(temp_download_path, ignore_errors=True)  # Delete the temporary directory

    return render_template('download.html')

def is_file_complete(file_path):
    """Check if the file download is complete by verifying file size consistency."""
    try:
        initial_size = os.path.getsize(file_path)
        time.sleep(2)  # Wait for a short period to allow file size to stabilize
        final_size = os.path.getsize(file_path)
        return initial_size == final_size
    except Exception as e:
        print(f"Error checking file completeness: {e}")
        return False



@app.route('/file_exists', methods=['POST'])
def handle_file_exists():
    if 'username' not in session:
        return redirect(url_for('index'))

    action = request.form.get('action')
    file_url = request.form.get('file_url')
    requested_file_name = request.form.get('requested_file_name')
    database = get_user_db(session['username'])
    conn = sqlite3.connect(database)
    cursor = conn.cursor()
    cursor.execute('SELECT save_path FROM user_config WHERE id = 1')
    save_path = cursor.fetchone()[0]
    conn.close()

    temp_download_path = tempfile.mkdtemp()  # Create a temporary directory

    if action == 'download_anyway':
        try:
            response = requests.get(file_url, stream=True)
            response.raise_for_status()

            with tempfile.NamedTemporaryFile(delete=False, dir=temp_download_path) as temp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)
                temp_file_path = temp_file.name

            file_hash = hashlib.sha256()
            with open(temp_file_path, 'rb') as f:
                while chunk := f.read(8192):
                    file_hash.update(chunk)
            file_hash = file_hash.hexdigest()

            file_size_mb = os.path.getsize(temp_file_path) / (1024 * 1024)
            download_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            dest_path = os.path.join(save_path, requested_file_name)
            shutil.copy(temp_file_path, dest_path)  # Copy file to permanent location

            conn = sqlite3.connect(database)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO datasets (file_name, file_path, file_hash, file_size_mb, download_timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (requested_file_name, dest_path, file_hash, file_size_mb, download_timestamp))
            conn.commit()
            conn.close()
            flash(f"File '{requested_file_name}' downloaded successfully and details stored.")
        except requests.exceptions.RequestException as e:
            flash(f"Failed to download file: {e}")
        finally:
            # Clean up temporary files
            os.remove(temp_file_path)  # Ensure the temp file is deleted if it exists
            shutil.rmtree(temp_download_path, ignore_errors=True)  # Delete the temporary directory

    elif action == 'skip_download':
        flash("Download skipped.")
        temp_file_path = os.path.join(temp_download_path, requested_file_name)
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)  # Remove the temporary file

    return redirect(url_for('download'))


@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('index'))

if __name__ == "__main__":
    app.run(debug=True)
