import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, g
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'secure_key_for_production'
DB_NAME = "gps_data.db"
TIMEOUT_THRESHOLD = 15

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- DATABASE SETUP ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_NAME)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'tracker'
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS shift_info (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                phone TEXT,
                duty TEXT,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                latitude REAL,
                longitude REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        db.commit()

# --- USER CLASS ---
class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row:
        return User(id=row['id'], username=row['username'], role=row['role'])
    return None

# --- AUTH ROUTES ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        hashed_pw = generate_password_hash(password)

        db = get_db()
        try:
            db.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", 
                       (username, hashed_pw, role))
            db.commit()
            flash('Account created successfully. Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already exists.', 'error')
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect_user_based_on_role(current_user)

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        db = get_db()
        user_row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        if user_row and check_password_hash(user_row['password_hash'], password):
            user = User(id=user_row['id'], username=user_row['username'], role=user_row['role'])
            login_user(user)
            return redirect_user_based_on_role(user)
        else:
            flash('Invalid credentials.', 'error')

    return render_template('login.html')

def redirect_user_based_on_role(user):
    if user.role == 'supervisor':
        return redirect(url_for('dashboard_view'))
    else:
        # Check if they already have shift info saved
        db = get_db()
        info = db.execute("SELECT * FROM shift_info WHERE user_id = ?", (user.id,)).fetchone()
        if info:
            return redirect(url_for('tracker_view')) # Skip form
        else:
            return redirect(url_for('start_duty')) # Show form

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

# --- APP ROUTES ---

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/start_duty', methods=['GET', 'POST'])
@login_required
def start_duty():
    if current_user.role != 'tracker':
        return redirect(url_for('dashboard_view'))

    if request.method == 'POST':
        full_name = request.form['full_name']
        phone = request.form['phone']
        duty = request.form['duty']

        db = get_db()
        db.execute('''
            INSERT OR REPLACE INTO shift_info (user_id, full_name, phone, duty, started_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (current_user.id, full_name, phone, duty))
        db.commit()
        return redirect(url_for('tracker_view'))

    return render_template('start_duty.html')

@app.route('/tracker')
@login_required
def tracker_view():
    if current_user.role != 'tracker':
        return redirect(url_for('dashboard_view'))
    return render_template('tracker.html', username=current_user.username)

@app.route('/dashboard')
@login_required
def dashboard_view():
    if current_user.role != 'supervisor':
        return redirect(url_for('tracker_view'))
    return render_template('dashboard.html')

# --- SUPERVISOR ACTIONS ---

@app.route('/reset_tracker/<int:user_id>')
@login_required
def reset_tracker(user_id):
    if current_user.role != 'supervisor':
        return redirect(url_for('tracker_view'))
    
    db = get_db()
    # Delete the shift info. Next time user logs in, they must re-enter it.
    db.execute("DELETE FROM shift_info WHERE user_id = ?", (user_id,))
    db.commit()
    flash("User data cleared. They will need to re-enter details next login.", "success")
    return redirect(url_for('dashboard_view'))

# --- API ROUTES ---

@app.route('/api/update_location', methods=['POST'])
@login_required
def update_location():
    data = request.json
    lat = data.get('latitude')
    lon = data.get('longitude')
    if lat and lon:
        db = get_db()
        db.execute("INSERT INTO locations (user_id, latitude, longitude) VALUES (?, ?, ?)", 
                   (current_user.id, lat, lon))
        db.commit()
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 400

@app.route('/api/get_live_data')
@login_required
def get_live_data():
    if current_user.role != 'supervisor':
        return jsonify({"error": "Unauthorized"}), 403

    db = get_db()
    query = '''
        SELECT u.id, u.username, s.full_name, s.phone, s.duty, l.latitude, l.longitude, l.timestamp
        FROM users u
        JOIN shift_info s ON u.id = s.user_id
        LEFT JOIN locations l ON u.id = l.user_id AND l.id = (SELECT MAX(id) FROM locations WHERE user_id = u.id)
        WHERE u.role = 'tracker'
    '''
    rows = db.execute(query).fetchall()
    results = []
    now = datetime.utcnow()

    for row in rows:
        status = "offline"
        seconds_ago = -1
        if row['timestamp']:
            last_active = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S')
            seconds_ago = int((now - last_active).total_seconds())
            if seconds_ago < TIMEOUT_THRESHOLD:
                status = "online"
        
        results.append({
            "id": row['id'],
            "username": row['username'],
            "full_name": row['full_name'],
            "phone": row['phone'],
            "duty": row['duty'],
            "status": status,
            "last_seen": seconds_ago,
            "latitude": row['latitude'],
            "longitude": row['longitude']
        })
    return jsonify(results)

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
