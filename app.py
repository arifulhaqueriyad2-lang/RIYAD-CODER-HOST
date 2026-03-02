from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
import os
import subprocess
import zipfile
import shutil
import json
import time
import threading
import psutil
import logging
import hashlib
import uuid
import secrets
from datetime import datetime
from werkzeug.utils import secure_filename
from functools import wraps

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1GB
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'py', 'js', 'zip', 'txt', 'html', 'css', 'json', 'md', 'sh', 'bash', 'log'}

# Admin credentials
ADMIN_USERNAME = "RIYAD"
ADMIN_PASSWORD_HASH = hashlib.sha256("CODER1234".encode()).hexdigest()

# User database (in memory for demo - use real database in production)
users_db = {
    "RIYAD": {
        "password_hash": ADMIN_PASSWORD_HASH,
        "is_admin": True,
        "created_at": datetime.now().isoformat()
    }
}

active_processes = {}

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def get_user_dir(username):
    user_dir = os.path.join(app.config['UPLOAD_FOLDER'], username)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session or not session.get('is_admin', False):
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return render_template('index.html', site_name="RIYAD CODER HOSTING")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        logger.info(f"Login attempt for username: {username}")
        
        # Check admin login
        if username == ADMIN_USERNAME and hashlib.sha256(password.encode()).hexdigest() == ADMIN_PASSWORD_HASH:
            session['username'] = username
            session['is_admin'] = True
            logger.info(f"Admin login successful: {username}")
            return redirect(url_for('admin_dashboard'))
        
        # Check if user exists in database
        if username in users_db:
            if users_db[username]['password_hash'] == hashlib.sha256(password.encode()).hexdigest():
                session['username'] = username
                session['is_admin'] = users_db[username].get('is_admin', False)
                logger.info(f"User login successful: {username}")
                return redirect(url_for('dashboard'))
        
        # If user doesn't exist, create new account
        if username not in users_db:
            users_db[username] = {
                "password_hash": hashlib.sha256(password.encode()).hexdigest(),
                "is_admin": False,
                "created_at": datetime.now().isoformat()
            }
            session['username'] = username
            session['is_admin'] = False
            logger.info(f"New user created: {username}")
            return redirect(url_for('dashboard'))
        
        # If password is wrong
        logger.warning(f"Login failed for username: {username}")
        return render_template('login.html', site_name="RIYAD CODER HOSTING", error="ভুল ইউজারনেম বা পাসওয়ার্ড")
    
    return render_template('login.html', site_name="RIYAD CODER HOSTING")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    username = session['username']
    user_dir = get_user_dir(username)
    
    # Get file list
    files = []
    try:
        for item in os.listdir(user_dir):
            item_path = os.path.join(user_dir, item)
            if os.path.isfile(item_path):
                files.append({
                    'name': item,
                    'size': format_size(os.path.getsize(item_path)),
                    'modified': datetime.fromtimestamp(os.path.getmtime(item_path)).strftime('%Y-%m-%d %H:%M:%S')
                })
    except Exception as e:
        logger.error(f"Error reading files for {username}: {e}")
    
    return render_template('dashboard.html', 
                         site_name="RIYAD CODER HOSTING",
                         username=username,
                         files=files[:10],  # Show only 10 recent files
                         is_admin=session.get('is_admin', False))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    # System stats
    cpu_percent = psutil.cpu_percent(interval=1)
    memory_percent = psutil.virtual_memory().percent
    disk_usage = psutil.disk_usage('/')
    
    # User list
    users = []
    for username in users_db.keys():
        user_dir = get_user_dir(username)
        file_count = 0
        storage_used = 0
        if os.path.exists(user_dir):
            try:
                files = os.listdir(user_dir)
                file_count = len([f for f in files if os.path.isfile(os.path.join(user_dir, f))])
                for f in files:
                    f_path = os.path.join(user_dir, f)
                    if os.path.isfile(f_path):
                        storage_used += os.path.getsize(f_path)
            except:
                pass
        
        users.append({
            'username': username,
            'file_count': file_count,
            'storage_used': format_size(storage_used),
            'is_admin': users_db[username].get('is_admin', False),
            'created_at': users_db[username].get('created_at', 'N/A')
        })
    
    return render_template('admin_dashboard.html',
                         site_name="RIYAD CODER HOSTING",
                         cpu_percent=cpu_percent,
                         memory_percent=memory_percent,
                         disk_total=format_size(disk_usage.total),
                         disk_used=format_size(disk_usage.used),
                         disk_percent=disk_usage.percent,
                         total_users=len(users_db),
                         users=users,
                         active_processes=[])

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_file():
    if request.method == 'POST':
        username = session['username']
        user_dir = get_user_dir(username)
        
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(user_dir, filename)
            file.save(file_path)
            
            # Handle zip files
            if filename.endswith('.zip'):
                try:
                    extract_path = os.path.join(user_dir, filename[:-4])
                    os.makedirs(extract_path, exist_ok=True)
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_path)
                    os.remove(file_path)
                except Exception as e:
                    logger.error(f"Error extracting zip: {e}")
            
            logger.info(f"File uploaded: {filename} by {username}")
            return jsonify({'success': True, 'message': 'ফাইল আপলোড সফল হয়েছে'})
        
        return jsonify({'error': 'File type not allowed'}), 400
    
    return render_template('upload.html', site_name="RIYAD CODER HOSTING")

@app.route('/files')
@login_required
def file_manager():
    username = session['username']
    user_dir = get_user_dir(username)
    
    files = []
    try:
        for item in os.listdir(user_dir):
            item_path = os.path.join(user_dir, item)
            if os.path.isfile(item_path):
                files.append({
                    'name': item,
                    'type': 'file',
                    'size': format_size(os.path.getsize(item_path)),
                    'modified': datetime.fromtimestamp(os.path.getmtime(item_path)).strftime('%Y-%m-%d %H:%M:%S'),
                    'extension': os.path.splitext(item)[1][1:] if '.' in item else ''
                })
            elif os.path.isdir(item_path):
                files.append({
                    'name': item,
                    'type': 'folder',
                    'size': '-',
                    'modified': datetime.fromtimestamp(os.path.getmtime(item_path)).strftime('%Y-%m-%d %H:%M:%S'),
                    'extension': 'folder'
                })
    except Exception as e:
        logger.error(f"Error listing files: {e}")
    
    return render_template('file_manager.html', 
                         site_name="RIYAD CODER HOSTING",
                         files=files,
                         username=username)

@app.route('/file/<path:filename>')
@login_required
def view_file(filename):
    username = session['username']
    user_dir = get_user_dir(username)
    file_path = os.path.join(user_dir, filename)
    
    if os.path.exists(file_path) and os.path.isfile(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return render_template('view_file.html',
                                 site_name="RIYAD CODER HOSTING",
                                 filename=filename,
                                 content=content,
                                 extension=os.path.splitext(filename)[1][1:] if '.' in filename else '')
        except UnicodeDecodeError:
            # Binary file
            return send_file(file_path, as_attachment=True)
    
    return redirect(url_for('file_manager'))

@app.route('/delete/<path:filename>', methods=['POST'])
@login_required
def delete_file(filename):
    username = session['username']
    user_dir = get_user_dir(username)
    file_path = os.path.join(user_dir, filename)
    
    try:
        if os.path.exists(file_path):
            if os.path.isfile(file_path):
                os.remove(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
            logger.info(f"File deleted: {filename} by {username}")
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
    
    return redirect(url_for('file_manager'))

@app.route('/run/<path:filename>', methods=['POST'])
@login_required
def run_file(filename):
    username = session['username']
    user_dir = get_user_dir(username)
    file_path = os.path.join(user_dir, filename)
    
    if os.path.exists(file_path) and os.path.isfile(file_path):
        extension = os.path.splitext(filename)[1][1:].lower()
        process_id = str(uuid.uuid4())
        
        try:
            if extension == 'py':
                process = subprocess.Popen(
                    ['python', file_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=user_dir
                )
            elif extension == 'js':
                process = subprocess.Popen(
                    ['node', file_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=user_dir
                )
            elif extension in ['sh', 'bash']:
                process = subprocess.Popen(
                    ['bash', file_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=user_dir
                )
            else:
                return jsonify({'error': 'Unsupported file type'}), 400
            
            active_processes[process_id] = {
                'process': process,
                'username': username,
                'command': f'{extension} {filename}',
                'start_time': time.time(),
                'output': []
            }
            
            return jsonify({
                'success': True,
                'process_id': process_id,
                'message': f'Started running {filename}'
            })
            
        except Exception as e:
            logger.error(f"Error running file: {e}")
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': 'File not found'}), 404

@app.route('/console')
@login_required
def console():
    return render_template('console.html', site_name="RIYAD CODER HOSTING")

@app.route('/api/console/execute', methods=['POST'])
@login_required
def console_execute():
    username = session['username']
    data = request.json
    command = data.get('command', '')
    
    user_dir = get_user_dir(username)
    
    try:
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=user_dir
        )
        
        stdout, stderr = process.communicate(timeout=30)
        
        return jsonify({
            'output': stdout + (stderr if stderr else ''),
            'error': bool(stderr)
        })
    except subprocess.TimeoutExpired:
        process.kill()
        return jsonify({'output': 'Command timed out', 'error': True})
    except Exception as e:
        return jsonify({'output': str(e), 'error': True})

@app.route('/api/process/<process_id>/output')
@login_required
def get_process_output(process_id):
    if process_id in active_processes:
        process_info = active_processes[process_id]
        
        if process_info['username'] != session['username'] and not session.get('is_admin', False):
            return jsonify({'error': 'Unauthorized'}), 403
        
        # Collect output
        process = process_info['process']
        outputs = []
        
        # Read available output
        if process.stdout:
            line = process.stdout.readline()
            if line:
                outputs.append(line)
        
        if process.stderr:
            line = process.stderr.readline()
            if line:
                outputs.append(f"ERROR: {line}")
        
        # Check if process completed
        returncode = process.poll()
        completed = returncode is not None
        
        if completed:
            # Get any remaining output
            stdout, stderr = process.communicate()
            if stdout:
                outputs.append(stdout)
            if stderr:
                outputs.append(f"ERROR: {stderr}")
        
        return jsonify({
            'outputs': outputs,
            'completed': completed
        })
    
    return jsonify({'error': 'Process not found'}), 404

@app.route('/api/process/<process_id>/stop', methods=['POST'])
@login_required
def stop_process(process_id):
    if process_id in active_processes:
        process_info = active_processes[process_id]
        
        if process_info['username'] != session['username'] and not session.get('is_admin', False):
            return jsonify({'error': 'Unauthorized'}), 403
        
        try:
            process_info['process'].terminate()
            process_info['process'].wait(timeout=5)
            return jsonify({'message': 'Process terminated'})
        except:
            process_info['process'].kill()
            return jsonify({'message': 'Process killed'})
        finally:
            del active_processes[process_id]
    
    return jsonify({'error': 'Process not found'}), 404

@app.route('/logs')
@login_required
def logs():
    return render_template('logs.html', site_name="RIYAD CODER HOSTING")

@app.route('/api/logs')
@login_required
def get_logs():
    username = session['username']
    user_dir = get_user_dir(username)
    
    log_files = []
    try:
        for f in os.listdir(user_dir):
            if f.endswith('.log') or f.endswith('.txt'):
                file_path = os.path.join(user_dir, f)
                if os.path.isfile(file_path):
                    log_files.append({
                        'name': f,
                        'size': format_size(os.path.getsize(file_path)),
                        'modified': datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M:%S')
                    })
    except Exception as e:
        logger.error(f"Error listing logs: {e}")
    
    return jsonify(log_files)

@app.route('/api/logs/<filename>')
@login_required
def view_log(filename):
    username = session['username']
    user_dir = get_user_dir(username)
    file_path = os.path.join(user_dir, filename)
    
    if os.path.exists(file_path) and os.path.isfile(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # Read last 1000 lines
                lines = f.readlines()[-1000:]
                return jsonify({'content': ''.join(lines)})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': 'File not found'}), 404

@app.route('/api/stats')
@login_required
def get_stats():
    username = session['username']
    user_dir = get_user_dir(username)
    
    total_files = 0
    storage_used = 0
    
    try:
        for f in os.listdir(user_dir):
            f_path = os.path.join(user_dir, f)
            if os.path.isfile(f_path):
                total_files += 1
                storage_used += os.path.getsize(f_path)
    except:
        pass
    
    return jsonify({
        'username': username,
        'total_files': total_files,
        'storage_used': format_size(storage_used),
        'server_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'active_processes': len([p for p in active_processes.values() if p['username'] == username])
    })

def format_size(size_bytes):
    if size_bytes == 0:
        return "0 B"
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.2f} {size_names[i]}"

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html', site_name="RIYAD CODER HOSTING"), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html', site_name="RIYAD CODER HOSTING"), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)