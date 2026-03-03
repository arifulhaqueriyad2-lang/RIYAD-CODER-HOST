from flask import Flask, render_template, request, redirect, url_for, session
import os
import zipfile
import subprocess
import signal
import shutil
import threading
import time

app = Flask(__name__)
app.secret_key = "mr_ghost_secret_key_123"

UPLOAD_FOLDER = "uploads"
MAX_RUNNING = 5

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# {(username, app_name): process}
processes = {}

# ---------- Helper ----------

def get_user_upload_path():
    user_dir = os.path.join(UPLOAD_FOLDER, session['username'])
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def extract_zip(zip_path, extract_to):
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(extract_to)

def install_requirements(path):
    req = os.path.join(path, "requirements.txt")
    if os.path.exists(req):
        subprocess.call(["pip", "install", "-r", req])

def find_main_file(path):
    for f in ["main.py", "app.py", "bot.py"]:
        if os.path.exists(os.path.join(path, f)):
            return f
    return None

# ---------- LOG STREAM ----------

def stream_logs(process, log_path):
    with open(log_path, "a", encoding="utf-8", errors="ignore") as f:
        for line in process.stdout:
            f.write(line)
            f.flush()

# ---------- APP CONTROL ----------

def start_app(app_name):
    user_dir = get_user_upload_path()
    app_dir = os.path.join(user_dir, app_name)
    zip_path = os.path.join(app_dir, "app.zip")
    extract_dir = os.path.join(app_dir, "extracted")
    log_path = os.path.join(app_dir, "logs.txt")

    os.makedirs(app_dir, exist_ok=True)

    if not os.path.exists(extract_dir):
        if not os.path.exists(zip_path):
            return
        extract_zip(zip_path, extract_dir)
        install_requirements(extract_dir)

    main_file = find_main_file(extract_dir)
    if not main_file:
        with open(log_path, "a") as f:
            f.write("❌ main.py / app.py / bot.py not found\n")
        return

    process = subprocess.Popen(
        ["python3", "-u", main_file],
        cwd=extract_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    threading.Thread(
        target=stream_logs,
        args=(process, log_path),
        daemon=True
    ).start()

    processes[(session['username'], app_name)] = process

def stop_app(app_name):
    key = (session['username'], app_name)
    p = processes.get(key)
    if p:
        try:
            p.terminate()
        except:
            pass
        processes.pop(key, None)

# ---------- ROUTES ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        if username:
            session['username'] = username  # এখানে পাসওয়ার্ড সিস্টেম যোগ করা যাবে
            return redirect(url_for("index"))
    return '''
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <body style="background:#0d0d0d; color:white; text-align:center; font-family:Arial; margin:0; padding:0;">
            <div style="display:flex; flex-direction:column; justify-content:center; align-items:center; height:100vh; padding:20px;">
                <h2 style="font-size:2em; margin-bottom:30px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                    Enter Your Name
                </h2>
                <form method="post" style="width:100%; max-width:350px;">
                    <input type="text" name="username" placeholder="Enter Username" required 
                           style="width:100%; padding:12px; font-size:1.1em; border-radius:8px; border:none; margin-bottom:15px;">
                    <button type="submit" 
                            style="width:100%; padding:12px; font-size:1.1em; background:#00ffcc; border:none; border-radius:8px; cursor:pointer;">
                        Enter Panel
                    </button>
                </form>
            </div>
        </body>
    '''

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/", methods=["GET", "POST"])
def index():
    if 'username' not in session:
        return redirect(url_for("login"))

    user_dir = get_user_upload_path()

    if request.method == "POST":
        file = request.files.get("file")
        if file and file.filename.endswith(".zip"):
            app_name = file.filename.replace(".zip", "")
            app_dir = os.path.join(user_dir, app_name)
            os.makedirs(app_dir, exist_ok=True)
            file.save(os.path.join(app_dir, "app.zip"))

    apps = []
    for name in os.listdir(user_dir):
        app_dir = os.path.join(user_dir, name)
        if not os.path.isdir(app_dir):
            continue

        log_file = os.path.join(app_dir, "logs.txt")
        log_data = "Waiting for logs..."

        if os.path.exists(log_file):
            with open(log_file, "r", errors="ignore") as f:
                data = f.read()
                if data.strip():
                    log_data = data[-4000:]

        apps.append({
            "name": name,
            "running": (session['username'], name) in processes,
            "log": log_data
        })

    return render_template("index.html", apps=apps)

@app.route("/run/<name>")
def run(name):
    if 'username' not in session:
        return redirect(url_for("login"))
    if (session['username'], name) not in processes and len(processes) < MAX_RUNNING:
        start_app(name)
    return redirect(url_for("index"))

@app.route("/stop/<name>")
def stop(name):
    if 'username' not in session:
        return redirect(url_for("login"))
    stop_app(name)
    return redirect(url_for("index"))

@app.route("/restart/<name>")
def restart(name):
    if 'username' not in session:
        return redirect(url_for("login"))
    stop_app(name)
    start_app(name)
    return redirect(url_for("index"))

@app.route("/delete/<name>")
def delete(name):
    if 'username' not in session:
        return redirect(url_for("login"))
    stop_app(name)
    shutil.rmtree(os.path.join(get_user_upload_path(), name), ignore_errors=True)
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8030, debug=False)