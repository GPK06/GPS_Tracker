import sqlite3
import time
from datetime import datetime
from flask import Flask, request, jsonify, render_template, g

app = Flask(__name__)
DB_NAME = "gps_data.db"

# Disconnect threshold value (in seconds)
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
        # Table to log history
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
        
@app.route('/')
# Home page
def index():
    return "<h2>Welcome. [/tracker for client, /dashboard for admin]</h2>"

# Client page
@app.route('/tracker')
def tracker():
    return render_template('tracker.html')

# Admin page
@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

# Recieve GPS Data from API
@app.route('/api/update_location', methods=['POST'])
def update_location():
    data = request.json
    user_id = data.get('user_id')
    lat = data.get('latitude')
    lon = data.get('longitude')

    # To throw error if data is improper
    if not user_id or not lat or not lon:
        return jsonify({"status": "error", "message": "Missing data"}), 400

    # Commit data to database
    db = get_db()
    cursor = db.cursor()
    cursor.execute("INSERT INTO locations (user_id, latitude, longitude) VALUES (?, ?, ?)", 
                   (user_id, lat, lon))
    db.commit()
    
    return jsonify({"status": "success"}), 200

# Status check
@app.route('/api/get_status/<user_id>')
def get_status(user_id):
    db = get_db()
    cursor = db.cursor()
    
    # Get the last entry for this user
    cursor.execute("SELECT timestamp, latitude, longitude FROM locations WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
    row = cursor.fetchone()

    # Disconnect status
    if not row:
        return jsonify({"status": "offline", "message": "No data found"})

    last_time_str = row[0]
    latitude = row[1]
    longitude = row[2]

    # Calculate time difference (in UTC - SQLite format)
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
    app.run(debug=True, host='0.0.0.0', port=5000)
