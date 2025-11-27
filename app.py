import sqlite3
import time
from datetime import datetime
from flask import Flask, request, jsonify, render_template, g

app = Flask(__name__)
DB_NAME = "gps_data.db"

# Config: How many seconds to wait before declaring "Disconnected"
TIMEOUT_THRESHOLD = 10 

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_NAME)
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
        # Create table to store history
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                latitude REAL,
                longitude REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        db.commit()

# --- ROUTES ---

@app.route('/')
def index():
    return "<h2>Go to /tracker to send GPS, or /dashboard to monitor.</h2>"

@app.route('/tracker')
def tracker_view():
    return render_template('tracker.html')

@app.route('/dashboard')
def dashboard_view():
    return render_template('dashboard.html')

# API to receive GPS data
@app.route('/api/update_location', methods=['POST'])
def update_location():
    data = request.json
    user_id = data.get('user_id')
    lat = data.get('latitude')
    lon = data.get('longitude')
    
    if not user_id or not lat or not lon:
        return jsonify({"status": "error", "message": "Missing data"}), 400

    db = get_db()
    cursor = db.cursor()
    cursor.execute("INSERT INTO locations (user_id, latitude, longitude) VALUES (?, ?, ?)", 
                   (user_id, lat, lon))
    db.commit()
    
    return jsonify({"status": "success"}), 200

# API to check status (Heartbeat monitor)
@app.route('/api/get_status/<user_id>')
def get_status(user_id):
    db = get_db()
    cursor = db.cursor()
    
    # Get the very last entry for this user
    cursor.execute("SELECT timestamp, latitude, longitude FROM locations WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        return jsonify({"status": "offline", "message": "No data found"})

    last_time_str = row[0]
    latitude = row[1]
    longitude = row[2]

    # Calculate time difference
    # SQLite stores time as UTC string usually, we convert to object
    last_active = datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S')
    now = datetime.utcnow()
    
    time_diff = (now - last_active).total_seconds()
    
    is_connected = time_diff < TIMEOUT_THRESHOLD
    
    return jsonify({
        "user_id": user_id,
        "status": "connected" if is_connected else "disconnected",
        "last_seen_seconds_ago": int(time_diff),
        "latitude": latitude,
        "longitude": longitude
    })

if __name__ == '__main__':
    init_db()
    # Host='0.0.0.0' allows access from other devices on the same WiFi
    app.run(debug=True, host='0.0.0.0', port=5000)