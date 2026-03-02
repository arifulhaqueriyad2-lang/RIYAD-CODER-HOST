from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from flask import make_response
import os
import subprocess
import zipfile
import shutil
import json
import time
import threading
import psutil
import logging
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from functools import wraps
import secrets
import hashlib
import uuid
from pathlib import Path
import sys
import queue
import asyncio
import signal
import re

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1GB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_FILES_PER_USER'] = 100
app.config['ALLOWED_EXTENSIONS'] = {'py', 'js', 'zip', 'txt', 'json', 'html', 'css', 'md', 'sh', 'bash'}

# Admin credentials (hashed for security)
ADMIN_USERNAME = "RIYAD"
ADMIN_PASSWORD_HASH = hashlib.sha256("CODER1234".encode()).hexdigest()

# User sessions storage
user_sessions = {}
active_processes = {}
process_outputs = {}

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create user directories
def get_user_dir(username):
    user_dir = os.path.join(app.config['UPLOAD_FOLDER'], username)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def get_user_files_dir(username):
    files_dir = os.path.join(get_user_dir(username), 'files')
    os.makedirs(files_dir, exist_ok=True)
    return files_dir

# Decorators
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
        if 'username' not in session or session.get('username') != ADMIN_USERNAME:
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def extract_zip(zip_path, extract_path):
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_path)

def get_file_size(file_path):
    return os.path.getsize(file_path) if os.path.exists(file_path) else 0

def get_user_storage_usage(username):
    user_dir = get_user_files_dir(username)
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(user_dir):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total_size += os.path.getsize(fp)
    return total_size

def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"

def check_requirements_txt(username):
    user_dir = get_user_files_dir(username)
    req_path = os.path.join(user_dir, 'requirements.txt')
    if os.path.exists(req_path):
        try:
            with open(req_path, 'r') as f:
                requirements = f.read().splitlines()
            return requirements
        except:
            return []
    return []

def install_requirements(username):
    user_dir = get_user_files_dir(username)
    req_path = os.path.join(user_dir, 'requirements.txt')
    if os.path.exists(req_path):
        try:
            subprocess.Popen(
                ['pip', 'install', '-r', req_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            return True
        except:
            return False
    return False

# Routes
@app.route('/')
def index():
    return render_template('index.html', site_name="RIYAD CODER HOSTING")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and hashlib.sha256(password.encode()).hexdigest() == ADMIN_PASSWORD_HASH:
            session['username'] = username
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            # Regular user login (simplified - in production, use proper user database)
            session['username'] = username
            session['is_admin'] = False
            return redirect(url_for('dashboard'))
    
    return render_template('login.html', site_name="RIYAD CODER HOSTING")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    username = session['username']
    user_dir = get_user_files_dir(username)
    
    # Get user statistics
    total_files = len([f for f in os.listdir(user_dir) if os.path.isfile(os.path.join(user_dir, f))])
    storage_used = get_user_storage_usage(username)
    storage_limit = 1024 * 1024 * 1024  # 1GB limit
    
    # Get recent files
    recent_files = []
    for f in os.listdir(user_dir)[:10]:
        file_path = os.path.join(user_dir, f)
        if os.path.isfile(file_path):
            recent_files.append({
                'name': f,
                'size': format_size(os.path.getsize(file_path)),
                'modified': datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M:%S')
            })
    
    return render_template('dashboard.html', 
                         site_name="RIYAD CODER HOSTING",
                         username=username,
                         total_files=total_files,
                         storage_used=format_size(storage_used),
                         storage_percent=(storage_used/storage_limit)*100,
                         recent_files=recent_files,
                         is_admin=session.get('is_admin', False))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    # Get system statistics
    cpu_percent = psutil.cpu_percent(interval=1)
    memory_percent = psutil.virtual_memory().percent
    disk_usage = psutil.disk_usage('/')
    
    # Get user statistics
    users = []
    for user_dir in os.listdir(app.config['UPLOAD_FOLDER']):
        user_path = os.path.join(app.config['UPLOAD_FOLDER'], user_dir)
        if os.path.isdir(user_path):
            files_dir = os.path.join(user_path, 'files')
            if os.path.exists(files_dir):
                file_count = len([f for f in os.listdir(files_dir) if os.path.isfile(os.path.join(files_dir, f))])
                storage_used = get_user_storage_usage(user_dir)
                users.append({
                    'username': user_dir,
                    'file_count': file_count,
                    'storage_used': format_size(storage_used),
                    'last_active': 'N/A'  # You can track this with a database
                })
    
    # Get active processes
    active_procs = []
    for pid, proc_info in active_processes.items():
        if proc_info['username'] in session.get('username', ''):
            active_procs.append({
                'pid': pid,
                'command': proc_info['command'],
                'start_time': datetime.fromtimestamp(proc_info['start_time']).strftime('%Y-%m-%d %H:%M:%S'),
                'username': proc_info['username']
            })
    
    return render_template('admin_dashboard.html',
                         site_name="RIYAD CODER HOSTING",
                         cpu_percent=cpu_percent,
                         memory_percent=memory_percent,
                         disk_total=format_size(disk_usage.total),
                         disk_used=format_size(disk_usage.used),
                         disk_percent=disk_usage.percent,
                         total_users=len(users),
                         users=users,
                         active_processes=active_procs)

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_file():
    username = session['username']
    user_dir = get_user_files_dir(username)
    
    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(user_dir, filename)
            file.save(file_path)
            
            # If it's a zip file, extract it
            if filename.endswith('.zip'):
                extract_path = os.path.join(user_dir, filename[:-4])
                os.makedirs(extract_path, exist_ok=True)
                extract_zip(file_path, extract_path)
                os.remove(file_path)  # Remove the zip after extraction
            
            # Check for requirements.txt and install
            if filename == 'requirements.txt':
                install_requirements(username)
            
            return redirect(url_for('file_manager'))
    
    return render_template('upload.html', site_name="RIYAD CODER HOSTING")

@app.route('/files')
@login_required
def file_manager():
    username = session['username']
    user_dir = get_user_files_dir(username)
    
    files = []
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
    
    return render_template('file_manager.html', 
                         site_name="RIYAD CODER HOSTING",
                         files=files,
                         username=username)

@app.route('/file/<path:filename>')
@login_required
def view_file(filename):
    username = session['username']
    user_dir = get_user_files_dir(username)
    file_path = os.path.join(user_dir, filename)
    
    if os.path.exists(file_path) and os.path.isfile(file_path):
        with open(file_path, 'r') as f:
            content = f.read()
        return render_template('view_file.html',
                             site_name="RIYAD CODER HOSTING",
                             filename=filename,
                             content=content,
                             extension=os.path.splitext(filename)[1][1:] if '.' in filename else '')
    
    return redirect(url_for('file_manager'))

@app.route('/delete/<path:filename>', methods=['POST'])
@login_required
def delete_file(filename):
    username = session['username']
    user_dir = get_user_files_dir(username)
    file_path = os.path.join(user_dir, filename)
    
    if os.path.exists(file_path):
        if os.path.isfile(file_path):
            os.remove(file_path)
        elif os.path.isdir(file_path):
            shutil.rmtree(file_path)
    
    return redirect(url_for('file_manager'))

@app.route('/run/<path:filename>', methods=['POST'])
@login_required
def run_file(filename):
    username = session['username']
    user_dir = get_user_files_dir(username)
    file_path = os.path.join(user_dir, filename)
    
    if os.path.exists(file_path) and os.path.isfile(file_path):
        extension = os.path.splitext(filename)[1][1:].lower()
        
        # Create a unique ID for this process
        process_id = str(uuid.uuid4())
        
        if extension == 'py':
            # Run Python file
            process = subprocess.Popen(
                ['python', file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                cwd=user_dir
            )
            
            # Store process info
            active_processes[process_id] = {
                'process': process,
                'username': username,
                'command': f'python {filename}',
                'start_time': time.time(),
                'output_queue': queue.Queue()
            }
            
            # Start output collection thread
            def collect_output():
                while True:
                    output = process.stdout.readline()
                    if output == '' and process.poll() is not None:
                        break
                    if output:
                        active_processes[process_id]['output_queue'].put(output)
                
                # Collect any remaining output
                stdout, stderr = process.communicate()
                if stdout:
                    active_processes[process_id]['output_queue'].put(stdout)
                if stderr:
                    active_processes[process_id]['output_queue'].put(f"ERROR: {stderr}")
                
                # Mark as completed
                active_processes[process_id]['completed'] = True
            
            threading.Thread(target=collect_output, daemon=True).start()
            
        elif extension == 'js':
            # Run JavaScript file with Node.js
            process = subprocess.Popen(
                ['node', file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                cwd=user_dir
            )
            
            active_processes[process_id] = {
                'process': process,
                'username': username,
                'command': f'node {filename}',
                'start_time': time.time(),
                'output_queue': queue.Queue()
            }
            
            def collect_output():
                while True:
                    output = process.stdout.readline()
                    if output == '' and process.poll() is not None:
                        break
                    if output:
                        active_processes[process_id]['output_queue'].put(output)
                
                stdout, stderr = process.communicate()
                if stdout:
                    active_processes[process_id]['output_queue'].put(stdout)
                if stderr:
                    active_processes[process_id]['output_queue'].put(f"ERROR: {stderr}")
                
                active_processes[process_id]['completed'] = True
            
            threading.Thread(target=collect_output, daemon=True).start()
        
        elif extension == 'sh' or extension == 'bash':
            # Run shell script
            process = subprocess.Popen(
                ['bash', file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                cwd=user_dir
            )
            
            active_processes[process_id] = {
                'process': process,
                'username': username,
                'command': f'bash {filename}',
                'start_time': time.time(),
                'output_queue': queue.Queue()
            }
            
            def collect_output():
                while True:
                    output = process.stdout.readline()
                    if output == '' and process.poll() is not None:
                        break
                    if output:
                        active_processes[process_id]['output_queue'].put(output)
                
                stdout, stderr = process.communicate()
                if stdout:
                    active_processes[process_id]['output_queue'].put(stdout)
                if stderr:
                    active_processes[process_id]['output_queue'].put(f"ERROR: {stderr}")
                
                active_processes[process_id]['completed'] = True
            
            threading.Thread(target=collect_output, daemon=True).start()
        
        else:
            return jsonify({'error': 'Unsupported file type'}), 400
        
        return jsonify({
            'process_id': process_id,
            'message': f'Started running {filename}'
        })
    
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
    
    # Security: Limit commands for regular users
    if not session.get('is_admin', False):
        allowed_commands = ['python', 'node', 'ls', 'pwd', 'echo', 'cat', 'grep']
        command_base = command.split()[0] if command else ''
        if command_base not in allowed_commands:
            return jsonify({'output': 'Command not allowed for regular users', 'error': True})
    
    user_dir = get_user_files_dir(username)
    
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
        
        # Check if user owns this process
        if process_info['username'] != session['username'] and not session.get('is_admin', False):
            return jsonify({'error': 'Unauthorized'}), 403
        
        outputs = []
        while not process_info['output_queue'].empty():
            outputs.append(process_info['output_queue'].get_nowait())
        
        return jsonify({
            'outputs': outputs,
            'completed': process_info.get('completed', False)
        })
    
    return jsonify({'error': 'Process not found'}), 404

@app.route('/api/process/<process_id>/stop', methods=['POST'])
@login_required
def stop_process(process_id):
    if process_id in active_processes:
        process_info = active_processes[process_id]
        
        # Check if user owns this process
        if process_info['username'] != session['username'] and not session.get('is_admin', False):
            return jsonify({'error': 'Unauthorized'}), 403
        
        try:
            process_info['process'].terminate()
            process_info['process'].wait(timeout=5)
            process_info['completed'] = True
            return jsonify({'message': 'Process terminated'})
        except:
            process_info['process'].kill()
            return jsonify({'message': 'Process killed'})
    
    return jsonify({'error': 'Process not found'}), 404

@app.route('/logs')
@login_required
def logs():
    return render_template('logs.html', site_name="RIYAD CODER HOSTING")

@app.route('/api/logs')
@login_required
def get_logs():
    username = session['username']
    user_dir = get_user_files_dir(username)
    
    # Get recent log files
    log_files = []
    for f in os.listdir(user_dir):
        if f.endswith('.log') or f.endswith('.txt'):
            file_path = os.path.join(user_dir, f)
            if os.path.isfile(file_path):
                log_files.append({
                    'name': f,
                    'size': format_size(os.path.getsize(file_path)),
                    'modified': datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M:%S')
                })
    
    return jsonify(log_files)

@app.route('/api/logs/<filename>')
@login_required
def view_log(filename):
    username = session['username']
    user_dir = get_user_files_dir(username)
    file_path = os.path.join(user_dir, filename)
    
    if os.path.exists(file_path) and os.path.isfile(file_path):
        try:
            with open(file_path, 'r') as f:
                # Read last 1000 lines for performance
                lines = f.readlines()[-1000:]
                return jsonify({'content': ''.join(lines)})
        except:
            return jsonify({'error': 'Could not read file'}), 500
    
    return jsonify({'error': 'File not found'}), 404

@app.route('/api/stats')
@login_required
def get_stats():
    username = session['username']
    user_dir = get_user_files_dir(username)
    
    stats = {
        'username': username,
        'total_files': len([f for f in os.listdir(user_dir) if os.path.isfile(os.path.join(user_dir, f))]),
        'storage_used': format_size(get_user_storage_usage(username)),
        'active_processes': len([p for p in active_processes.values() if p['username'] == username]),
        'server_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    return jsonify(stats)

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html', site_name="RIYAD CODER HOSTING"), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html', site_name="RIYAD CODER HOSTING"), 500

# Cleanup old processes
def cleanup_processes():
    while True:
        current_time = time.time()
        to_remove = []
        
        for pid, proc_info in active_processes.items():
            # Remove processes older than 1 hour
            if current_time - proc_info['start_time'] > 3600:
                if 'process' in proc_info:
                    try:
                        proc_info['process'].terminate()
                    except:
                        pass
                to_remove.append(pid)
        
        for pid in to_remove:
            del active_processes[pid]
        
        time.sleep(300)  # Run every 5 minutes

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_processes, daemon=True)
cleanup_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)