import os
import re
import math
import hashlib
import secrets
import smtplib
import json
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, join_room, leave_room, emit
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
if not app.config["SECRET_KEY"]:
    raise RuntimeError("SECRET_KEY environment variable is required. Copy .env.example to .env and set it.")

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///sfu_connect.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV") == "production"
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins=[], manage_session=True, async_mode="eventlet")
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=["300 per day", "80 per hour"])

# ---------------------------------------------------------
# MODELS
# ---------------------------------------------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    student_number = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    faculty = db.Column(db.String(150), default="")
    course = db.Column(db.String(150), default="")
    year_of_study = db.Column(db.String(30), default="")
    bio = db.Column(db.String(2000), default="")
    headline = db.Column(db.String(200), default="")
    skills = db.Column(db.Text, default="")
    interests = db.Column(db.Text, default="")
    portfolio_json = db.Column(db.Text, default="[]")
    is_mentor = db.Column(db.Boolean, default=False)
    discoverable = db.Column(db.Boolean, default=True)
    show_location = db.Column(db.Boolean, default=True)
    show_portfolio = db.Column(db.Boolean, default=True)
    show_skills = db.Column(db.Boolean, default=True)
    email_verified = db.Column(db.Boolean, default=False)
    identity_verified = db.Column(db.Boolean, default=False)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    location_updated_at = db.Column(db.DateTime, nullable=True)
    role = db.Column(db.String(30), default="student")
    verification_token_hash = db.Column(db.String(128), nullable=True)
    verification_expires = db.Column(db.DateTime, nullable=True)
    reset_token_hash = db.Column(db.String(128), nullable=True)
    reset_expires = db.Column(db.DateTime, nullable=True)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    faculty = db.Column(db.String(150), default="")
    topic = db.Column(db.String(150), default="")
    description = db.Column(db.String(2000), default="")
    owner_id = db.Column(db.Integer, nullable=False)
    is_private = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Membership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    group_id = db.Column(db.Integer, nullable=False)
    role = db.Column(db.String(30), default="member")
    __table_args__ = (db.UniqueConstraint("user_id", "group_id", name="unique_group_membership"),)

class Status(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    body = db.Column(db.String(1000), nullable=False)
    achievement = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class GroupPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    body = db.Column(db.String(3000), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    owner_id = db.Column(db.Integer, nullable=False)
    active = db.Column(db.Boolean, default=True)
    scheduled_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    faculty = db.Column(db.String(150), default="")
    looking_for = db.Column(db.String(500), default="")
    owner_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), default="open")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ProjectMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    role = db.Column(db.String(50), default="member")
    __table_args__ = (db.UniqueConstraint("project_id", "user_id", name="unique_project_member"),)

class SkillExchange(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_user_id = db.Column(db.Integer, nullable=False)
    to_user_id = db.Column(db.Integer, nullable=True)
    offer_skill = db.Column(db.String(120), nullable=False)
    request_skill = db.Column(db.String(120), nullable=False)
    message = db.Column(db.String(1000), default="")
    status = db.Column(db.String(30), default="open")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.String(1000), default="")
    link = db.Column(db.String(300), default="")
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, nullable=False)
    target_type = db.Column(db.String(50), nullable=False)
    target_id = db.Column(db.String(100), nullable=False)
    reason = db.Column(db.String(100), nullable=False)
    details = db.Column(db.String(1000), default="")
    status = db.Column(db.String(30), default="open")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Block(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, nullable=False)
    blocked_id = db.Column(db.Integer, nullable=False)
    __table_args__ = (db.UniqueConstraint("blocker_id", "blocked_id", name="unique_block"),)

# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------
def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    user = db.session.get(User, uid)
    if user:
        user.last_active = datetime.utcnow()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    return user

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user():
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return wrapped

def csrf_required():
    token = request.headers.get("X-CSRF-Token")
    if not token:
        return False
    return secrets.compare_digest(token, session.get("csrf_token", ""))

def create_csrf():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]

def clean_text(value, maximum):
    if not isinstance(value, str):
        return ""
    return value.strip()[:maximum]

def valid_sfu_email(email):
    return bool(re.fullmatch(r"[^@\s]+@sfu\.ca", email.lower()))

def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))

def is_member(user_id, group_id):
    return Membership.query.filter_by(user_id=user_id, group_id=group_id).first() is not None

def blocked_between(u1, u2):
    return Block.query.filter(
        ((Block.blocker_id == u1) & (Block.blocked_id == u2)) |
        ((Block.blocker_id == u2) & (Block.blocked_id == u1))
    ).first() is not None

def moderate_text(text):
    patterns = [
        r"\bkill\s+you\b", r"\bgo\s+die\b", r"\bi\s+will\s+hurt\s+you\b",
        r"\brape\s+you\b", r"\bsend\s+nudes\b", r"\bkill\s+yourself\b"
    ]
    lowered = text.lower()
    return not any(re.search(p, lowered) for p in patterns)

def parse_skills(skills_str):
    if not skills_str:
        return []
    return [s.strip().lower() for s in re.split(r"[,;|]", skills_str) if s.strip()]

def create_notification(user_id, title, body="", link=""):
    n = Notification(user_id=user_id, title=title, body=body, link=link)
    db.session.add(n)
    db.session.commit()
    socketio.emit("new_notification", {
        "id": n.id, "title": title, "body": body, "link": link,
        "created_at": n.created_at.isoformat()
    }, room=f"user-{user_id}")

def send_email(to_email, subject, body):
    smtp_host = os.environ.get("SMTP_HOST")
    if not smtp_host:
        print(f"\n[DEV EMAIL] To: {to_email}\nSubject: {subject}\n{body}\n")
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("MAIL_FROM") or os.environ.get("SMTP_USER")
    msg["To"] = to_email
    msg.set_content(body)
    with smtplib.SMTP(smtp_host, int(os.environ.get("SMTP_PORT", 587)), timeout=10) as server:
        server.starttls()
        user = os.environ.get("SMTP_USER")
        pwd = os.environ.get("SMTP_PASSWORD")
        if user and pwd:
            server.login(user, pwd)
        server.send_message(msg)

def send_verification_email(user, token):
    base = os.environ.get("APP_BASE_URL", "http://localhost:5000")
    url = f"{base}/verify-email/{token}"
    send_email(user.email, "Verify your SFU Connect account",
               f"Welcome to SFU Connect.\n\nVerify your account:\n{url}\n\nThis link expires in 2 hours.")

def ai_assist(prompt, user_context=""):
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        try:
            import urllib.request
            payload = {
                "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                "messages": [
                    {"role": "system", "content": "You are a helpful academic assistant for Simon Fraser University students. Be concise, practical and encouraging."},
                    {"role": "user", "content": f"Context: {user_context}\n\nRequest: {prompt}"}
                ],
                "max_tokens": 700
            }
            req = urllib.request.Request(
                f"{os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')}/chat/completions",
                data=json.dumps(payload).encode(),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
                return data["choices"][0]["message"]["content"]
        except Exception:
            pass

    p = prompt.lower()
    if "cv" in p or "resume" in p:
        return ("CV tips for SFU students:\n"
                "1. Put your SFU degree and expected graduation near the top.\n"
                "2. Quantify impact (e.g. 'Improved query performance by 40%').\n"
                "3. List technical skills and tools explicitly.\n"
                "4. Include 1–2 relevant projects with links or GitHub.\n"
                "5. Keep it to one page unless you have significant experience.")
    if "skill" in p or "learn" in p:
        return ("Skill development suggestion:\n"
                "Identify the gap → find a small project that forces you to use the skill → "
                "join or create a study group → teach someone else what you just learned. "
                "Teaching is the fastest way to solidify knowledge.")
    if "project" in p or "collaborat" in p:
        return ("Project collaboration advice:\n"
                "Write a clear one-paragraph problem statement, list the exact skills you need, "
                "set a realistic milestone for the next 2 weeks, and invite people who already "
                "have complementary strengths. Start small and ship something visible.")
    return ("I'm here to help with academic planning, skill development, CV improvement, "
            "project ideas and study strategies. Try asking something more specific, "
            "for example: 'Help me improve my CV for a software internship' or "
            "'Suggest a project that uses React and Python'.")

# ---------------------------------------------------------
# SECURITY HEADERS
# ---------------------------------------------------------
@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=(self)"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self' ws: wss:; img-src 'self' data:; media-src 'self' blob:; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self';"
    )
    return response

# ---------------------------------------------------------
# FRONTEND + CSRF
# ---------------------------------------------------------
@app.get("/")
def home():
    return render_template("index.html")

@app.get("/api/csrf")
def csrf():
    return jsonify({"csrf_token": create_csrf()})

@app.get("/api/webrtc-config")
@login_required
def webrtc_config():
    ice = [{"urls": "stun:stun.l.google.com:19302"}]
    turn_urls = os.environ.get("TURN_URLS", "").strip()
    if turn_urls:
        ice.append({
            "urls": [u.strip() for u in turn_urls.split(",") if u.strip()],
            "username": os.environ.get("TURN_USERNAME", ""),
            "credential": os.environ.get("TURN_CREDENTIAL", "")
        })
    return jsonify({"iceServers": ice})

# ---------------------------------------------------------
# AUTH
# ---------------------------------------------------------
@app.post("/api/register")
@limiter.limit("5 per hour")
def register():
    data = request.get_json() or {}
    name = clean_text(data.get("name"), 120)
    student_number = clean_text(data.get("student_number"), 50)
    email = clean_text(data.get("email"), 180).lower()
    password = data.get("password", "")
    faculty = clean_text(data.get("faculty"), 150)
    course = clean_text(data.get("course"), 150)

    if not name or not student_number:
        return jsonify({"error": "Name and student number are required."}), 400
    if not valid_sfu_email(email):
        return jsonify({"error": "Use a valid @sfu.ca student email."}), 400
    if len(password) < 12:
        return jsonify({"error": "Password must be at least 12 characters."}), 400

    if User.query.filter((User.email == email) | (User.student_number == student_number)).first():
        return jsonify({"error": "An account with those details already exists."}), 409

    user = User(
        name=name, student_number=student_number, email=email,
        password_hash=generate_password_hash(password),
        faculty=faculty, course=course
    )
    token = secrets.token_urlsafe(32)
    user.verification_token_hash = hash_token(token)
    user.verification_expires = datetime.utcnow() + timedelta(hours=2)
    db.session.add(user)
    db.session.commit()
    send_verification_email(user, token)
    return jsonify({"message": "Account created. Check your SFU email to verify."}), 201

@app.get("/verify-email/<token>")
def verify_email(token):
    user = User.query.filter_by(verification_token_hash=hash_token(token)).first()
    if not user or not user.verification_expires or user.verification_expires < datetime.utcnow():
        return "Invalid or expired verification link.", 400
    user.email_verified = True
    user.verification_token_hash = None
    user.verification_expires = None
    db.session.commit()
    return """<!DOCTYPE html><html><body style="font-family:system-ui;text-align:center;padding:80px">
        <h1>SFU Connect</h1><h2>Email verified successfully</h2>
        <p>You can now return to the app and log in.</p></body></html>"""

@app.post("/api/login")
@limiter.limit("10 per 15 minutes")
def login():
    data = request.get_json() or {}
    email = clean_text(data.get("email"), 180).lower()
    password = data.get("password", "")
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid email or password."}), 401
    if not user.email_verified:
        return jsonify({"error": "Please verify your SFU email first."}), 403
    session.clear()
    session["user_id"] = user.id
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify({"message": "Logged in successfully."})

@app.post("/api/logout")
@login_required
def logout():
    if not csrf_required():
        return jsonify({"error": "Invalid CSRF token."}), 403
    session.clear()
    return jsonify({"message": "Logged out."})

@app.post("/api/forgot-password")
@limiter.limit("5 per hour")
def forgot_password():
    data = request.get_json() or {}
    email = clean_text(data.get("email"), 180).lower()
    user = User.query.filter_by(email=email).first()
    if user:
        token = secrets.token_urlsafe(32)
        user.reset_token_hash = hash_token(token)
        user.reset_expires = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()
        base = os.environ.get("APP_BASE_URL", "http://localhost:5000")
        send_email(user.email, "Reset your SFU Connect password",
                   f"Reset link (valid 1 hour):\n{base}/#reset={token}")
    return jsonify({"message": "If that email exists, a reset link has been sent."})

@app.post("/api/reset-password")
@limiter.limit("5 per hour")
def reset_password():
    data = request.get_json() or {}
    token = data.get("token", "")
    password = data.get("password", "")
    if len(password) < 12:
        return jsonify({"error": "Password must be at least 12 characters."}), 400
    user = User.query.filter_by(reset_token_hash=hash_token(token)).first()
    if not user or not user.reset_expires or user.reset_expires < datetime.utcnow():
        return jsonify({"error": "Invalid or expired reset token."}), 400
    user.password_hash = generate_password_hash(password)
    user.reset_token_hash = None
    user.reset_expires = None
    db.session.commit()
    return jsonify({"message": "Password updated. You can now log in."})

# ---------------------------------------------------------
# CURRENT USER + PROFILE + PORTFOLIO
# ---------------------------------------------------------
@app.get("/api/me")
@login_required
def me():
    u = current_user()
    return jsonify({
        "id": u.id, "name": u.name, "student_number": u.student_number, "email": u.email,
        "faculty": u.faculty, "course": u.course, "year_of_study": u.year_of_study,
        "bio": u.bio, "headline": u.headline, "skills": u.skills, "interests": u.interests,
        "portfolio_json": u.portfolio_json, "is_mentor": u.is_mentor,
        "discoverable": u.discoverable, "show_location": u.show_location,
        "show_portfolio": u.show_portfolio, "show_skills": u.show_skills,
        "email_verified": u.email_verified, "identity_verified": u.identity_verified
    })

@app.patch("/api/me")
@login_required
def update_me():
    if not csrf_required():
        return jsonify({"error": "Invalid CSRF token."}), 403
    u = current_user()
    data = request.get_json() or {}
    for field, max_len in [
        ("name", 120), ("faculty", 150), ("course", 150), ("year_of_study", 30),
        ("bio", 2000), ("headline", 200), ("skills", 2000), ("interests", 1000)
    ]:
        if field in data:
            setattr(u, field, clean_text(data[field], max_len))
    if "portfolio_json" in data:
        try:
            raw = data["portfolio_json"]
            if not isinstance(raw, str):
                raw = json.dumps(raw)
            json.loads(raw)
            u.portfolio_json = raw
        except Exception:
            return jsonify({"error": "Invalid portfolio data."}), 400
    for flag in ["is_mentor", "discoverable", "show_location", "show_portfolio", "show_skills"]:
        if flag in data:
            setattr(u, flag, bool(data[flag]))
            if flag == "discoverable" and not u.discoverable:
                u.latitude = None
                u.longitude = None
    db.session.commit()
    return jsonify({"message": "Profile updated."})

@app.get("/api/portfolio/<int:user_id>")
@login_required
def public_portfolio(user_id):
    target = db.session.get(User, user_id)
    if not target or not target.show_portfolio:
        return jsonify({"error": "Portfolio not available."}), 404
    if blocked_between(current_user().id, user_id):
        return jsonify({"error": "Not available."}), 403
    return jsonify({
        "id": target.id, "name": target.name, "faculty": target.faculty,
        "course": target.course, "year_of_study": target.year_of_study,
        "headline": target.headline, "bio": target.bio,
        "skills": target.skills if target.show_skills else "",
        "portfolio": json.loads(target.portfolio_json or "[]"),
        "identity_verified": target.identity_verified
    })

@app.get("/api/cv")
@login_required
def generate_cv():
    u = current_user()
    portfolio = json.loads(u.portfolio_json or "[]")
    skills = ", ".join(parse_skills(u.skills))
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>CV – {u.name}</title>
    <style>
        body{{font-family:system-ui,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;color:#111}}
        h1{{margin:0 0 4px;font-size:28px}} h2{{border-bottom:2px solid #7c3aed;padding-bottom:4px;margin-top:28px;font-size:18px}}
        .meta{{color:#555;margin-bottom:20px}} .item{{margin-bottom:14px}} .item strong{{display:block}}
    </style></head><body>
    <h1>{u.name}</h1>
    <div class="meta">{u.email} · {u.faculty} · {u.course} {u.year_of_study}</div>
    <p>{u.headline or u.bio}</p>
    <h2>Skills</h2><p>{skills or '—'}</p>
    <h2>Portfolio & Experience</h2>"""
    for item in portfolio:
        html += f"""<div class="item"><strong>{item.get('title','')}</strong>
        <span>{item.get('subtitle','')} {item.get('date','')}</span>
        <p>{item.get('description','')}</p></div>"""
    html += "</body></html>"
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html"
    return resp

# ---------------------------------------------------------
# LOCATION + AROUND ME + PEOPLE YOU MAY KNOW
# ---------------------------------------------------------
@app.post("/api/location")
@login_required
def update_location():
    if not csrf_required():
        return jsonify({"error": "Invalid CSRF token."}), 403
    u = current_user()
    data = request.get_json() or {}
    try:
        lat = float(data["latitude"])
        lon = float(data["longitude"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Invalid location."}), 400
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify({"error": "Invalid coordinates."}), 400
    if not u.discoverable or not u.show_location:
        return jsonify({"error": "Enable discoverability and location sharing first."}), 403
    u.latitude = round(lat, 3)
    u.longitude = round(lon, 3)
    u.location_updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"message": "Approximate location updated."})

@app.get("/api/around-me")
@login_required
def around_me():
    u = current_user()
    if u.latitude is None:
        return jsonify({"error": "Share your location first."}), 400
    radius = min(max(float(request.args.get("radius_km", 8)), 1), 30)
    cutoff = datetime.utcnow() - timedelta(hours=36)

    mentors = []
    for m in User.query.filter(
        User.id != u.id, User.is_mentor == True, User.discoverable == True,
        User.show_location == True, User.latitude.isnot(None),
        User.location_updated_at >= cutoff
    ).all():
        if blocked_between(u.id, m.id):
            continue
        dist = haversine(u.latitude, u.longitude, m.latitude, m.longitude)
        if dist <= radius:
            mentors.append({
                "id": m.id, "name": m.name, "faculty": m.faculty,
                "skills": m.skills if m.show_skills else "",
                "headline": m.headline, "distance_km": round(dist, 1),
                "identity_verified": m.identity_verified
            })
    mentors.sort(key=lambda x: x["distance_km"])

    my_groups = [m.group_id for m in Membership.query.filter_by(user_id=u.id).all()]
    active_rooms = []
    if my_groups:
        for r in Room.query.filter(Room.group_id.in_(my_groups), Room.active == True).order_by(Room.created_at.desc()).limit(10):
            g = db.session.get(Group, r.group_id)
            active_rooms.append({"id": r.id, "name": r.name, "group_name": g.name if g else ""})

    projects = []
    for p in Project.query.filter_by(status="open").order_by(Project.created_at.desc()).limit(15):
        if p.faculty and u.faculty and p.faculty.lower() != u.faculty.lower():
            continue
        projects.append({"id": p.id, "title": p.title, "looking_for": p.looking_for, "faculty": p.faculty})

    return jsonify({"mentors": mentors[:12], "active_rooms": active_rooms, "projects": projects})

@app.get("/api/people-you-may-know")
@login_required
def people_you_may_know():
    u = current_user()
    my_skills = set(parse_skills(u.skills))
    my_groups = {m.group_id for m in Membership.query.filter_by(user_id=u.id).all()}
    candidates = []
    for other in User.query.filter(User.id != u.id, User.discoverable == True).limit(100):
        if blocked_between(u.id, other.id):
            continue
        score = 0
        reasons = []
        if u.faculty and other.faculty and u.faculty.lower() == other.faculty.lower():
            score += 3
            reasons.append("Same faculty")
        if u.course and other.course and u.course.lower() == other.course.lower():
            score += 4
            reasons.append("Same programme")
        other_skills = set(parse_skills(other.skills))
        overlap = my_skills & other_skills
        if overlap:
            score += len(overlap) * 2
            reasons.append("Shared skills: " + ", ".join(list(overlap)[:3]))
        other_groups = {m.group_id for m in Membership.query.filter_by(user_id=other.id).all()}
        shared_g = my_groups & other_groups
        if shared_g:
            score += len(shared_g) * 3
            reasons.append("Shared groups")
        if score > 0:
            candidates.append({
                "id": other.id, "name": other.name, "faculty": other.faculty,
                "course": other.course, "headline": other.headline,
                "skills": other.skills if other.show_skills else "",
                "score": score, "reasons": reasons, "identity_verified": other.identity_verified
            })
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return jsonify({"people": candidates[:15]})

# ---------------------------------------------------------
# SKILL EXCHANGE
# ---------------------------------------------------------
@app.get("/api/skill-exchanges")
@login_required
def list_skill_exchanges():
    items = SkillExchange.query.filter_by(status="open").order_by(SkillExchange.created_at.desc()).limit(40).all()
    result = []
    for s in items:
        owner = db.session.get(User, s.from_user_id)
        if not owner or blocked_between(current_user().id, owner.id):
            continue
        result.append({
            "id": s.id, "from_user": {"id": owner.id, "name": owner.name},
            "offer_skill": s.offer_skill, "request_skill": s.request_skill,
            "message": s.message, "created_at": s.created_at.isoformat()
        })
    return jsonify(result)

@app.post("/api/skill-exchanges")
@login_required
def create_skill_exchange():
    if not csrf_required():
        return jsonify({"error": "Invalid CSRF token."}), 403
    data = request.get_json() or {}
    offer = clean_text(data.get("offer_skill"), 120)
    request_skill = clean_text(data.get("request_skill"), 120)
    message = clean_text(data.get("message"), 1000)
    if not offer or not request_skill:
        return jsonify({"error": "Both offer and request skills are required."}), 400
    s = SkillExchange(from_user_id=current_user().id, offer_skill=offer,
                      request_skill=request_skill, message=message)
    db.session.add(s)
    db.session.commit()
    return jsonify({"message": "Skill exchange offer created.", "id": s.id}), 201

# ---------------------------------------------------------
# PROJECTS
# ---------------------------------------------------------
@app.get("/api/projects")
@login_required
def list_projects():
    projects = Project.query.order_by(Project.created_at.desc()).limit(50).all()
    result = []
    for p in projects:
        owner = db.session.get(User, p.owner_id)
        members = ProjectMember.query.filter_by(project_id=p.id).count()
        result.append({
            "id": p.id, "title": p.title, "description": p.description,
            "faculty": p.faculty, "looking_for": p.looking_for,
            "status": p.status, "owner_name": owner.name if owner else "",
            "members": members, "created_at": p.created_at.isoformat()
        })
    return jsonify(result)

@app.post("/api/projects")
@login_required
def create_project():
    if not csrf_required():
        return jsonify({"error": "Invalid CSRF token."}), 403
    data = request.get_json() or {}
    title = clean_text(data.get("title"), 200)
    if not title:
        return jsonify({"error": "Title is required."}), 400
    p = Project(
        title=title,
        description=clean_text(data.get("description"), 3000),
        faculty=clean_text(data.get("faculty"), 150) or current_user().faculty,
        looking_for=clean_text(data.get("looking_for"), 500),
        owner_id=current_user().id
    )
    db.session.add(p)
    db.session.flush()
    db.session.add(ProjectMember(project_id=p.id, user_id=current_user().id, role="owner"))
    db.session.commit()
    return jsonify({"message": "Project created.", "id": p.id}), 201

@app.post("/api/projects/<int:project_id>/join")
@login_required
def join_project(project_id):
    if not csrf_required():
        return jsonify({"error": "Invalid CSRF token."}), 403
    p = db.session.get(Project, project_id)
    if not p or p.status != "open":
        return jsonify({"error": "Project not available."}), 404
    existing = ProjectMember.query.filter_by(project_id=project_id, user_id=current_user().id).first()
    if not existing:
        db.session.add(ProjectMember(project_id=project_id, user_id=current_user().id))
        db.session.commit()
        create_notification(p.owner_id, "New project member",
                            f"{current_user().name} joined your project “{p.title}”.",
                            "#projects")
    return jsonify({"message": "Joined project."})

# ---------------------------------------------------------
# FEED, GROUPS, ROOMS, REPORTS
# ---------------------------------------------------------
@app.get("/api/feed")
@login_required
def feed():
    statuses = Status.query.order_by(Status.created_at.desc()).limit(40).all()
    result = []
    me = current_user()
    for s in statuses:
        user = db.session.get(User, s.user_id)
        if not user or blocked_between(me.id, user.id):
            continue
        result.append({
            "id": s.id, "user_id": user.id, "name": user.name, "faculty": user.faculty,
            "body": s.body, "achievement": s.achievement, "created_at": s.created_at.isoformat()
        })
    return jsonify(result)

@app.post("/api/status")
@login_required
@limiter.limit("20 per hour")
def create_status():
    if not csrf_required():
        return jsonify({"error": "Invalid CSRF token."}), 403
    data = request.get_json() or {}
    body = clean_text(data.get("body"), 1000)
    if not body:
        return jsonify({"error": "Status cannot be empty."}), 400
    if not moderate_text(body):
        return jsonify({"error": "Content blocked by community rules."}), 400
    s = Status(user_id=current_user().id, body=body, achievement=bool(data.get("achievement")))
    db.session.add(s)
    db.session.commit()
    return jsonify({"message": "Status posted."}), 201

@app.get("/api/groups")
@login_required
def groups():
    groups = Group.query.order_by(Group.created_at.desc()).all()
    result = []
    me = current_user()
    for g in groups:
        count = Membership.query.filter_by(group_id=g.id).count()
        result.append({
            "id": g.id, "name": g.name, "faculty": g.faculty, "topic": g.topic,
            "description": g.description, "members": count,
            "joined": is_member(me.id, g.id), "is_private": g.is_private
        })
    return jsonify(result)

@app.post("/api/groups")
@login_required
def create_group():
    if not csrf_required():
        return jsonify({"error": "Invalid CSRF token."}), 403
    data = request.get_json() or {}
    name = clean_text(data.get("name"), 150)
    if not name:
        return jsonify({"error": "Group name is required."}), 400
    g = Group(
        name=name, faculty=clean_text(data.get("faculty"), 150),
        topic=clean_text(data.get("topic"), 150),
        description=clean_text(data.get("description"), 2000),
        owner_id=current_user().id, is_private=bool(data.get("is_private"))
    )
    db.session.add(g)
    db.session.flush()
    db.session.add(Membership(user_id=current_user().id, group_id=g.id, role="owner"))
    db.session.commit()
    return jsonify({"message": "Group created.", "group_id": g.id}), 201

@app.post("/api/groups/<int:group_id>/join")
@login_required
def join_group(group_id):
    if not csrf_required():
        return jsonify({"error": "Invalid CSRF token."}), 403
    g = db.session.get(Group, group_id)
    if not g:
        return jsonify({"error": "Group not found."}), 404
    if not is_member(current_user().id, group_id):
        db.session.add(Membership(user_id=current_user().id, group_id=group_id))
        db.session.commit()
    return jsonify({"message": "Joined group."})

@app.get("/api/groups/<int:group_id>/posts")
@login_required
def group_posts(group_id):
    if not is_member(current_user().id, group_id):
        return jsonify({"error": "Join this group first."}), 403
    posts = GroupPost.query.filter_by(group_id=group_id).order_by(GroupPost.created_at.desc()).limit(80).all()
    result = []
    for p in posts:
        user = db.session.get(User, p.user_id)
        if user:
            result.append({
                "id": p.id, "user_id": user.id, "name": user.name,
                "body": p.body, "created_at": p.created_at.isoformat()
            })
    return jsonify(result)

@app.post("/api/groups/<int:group_id>/posts")
@login_required
@limiter.limit("30 per hour")
def create_group_post(group_id):
    if not csrf_required():
        return jsonify({"error": "Invalid CSRF token."}), 403
    if not is_member(current_user().id, group_id):
        return jsonify({"error": "Join the group first."}), 403
    data = request.get_json() or {}
    body = clean_text(data.get("body"), 3000)
    if not body or not moderate_text(body):
        return jsonify({"error": "Invalid or blocked content."}), 400
    post = GroupPost(group_id=group_id, user_id=current_user().id, body=body)
    db.session.add(post)
    db.session.commit()
    members = Membership.query.filter_by(group_id=group_id).all()
    for m in members:
        if m.user_id != current_user().id:
            create_notification(m.user_id, "New group post",
                                f"{current_user().name} posted in a group you belong to.",
                                "#groups")
    return jsonify({"message": "Post created."}), 201

@app.get("/api/rooms")
@login_required
def rooms():
    my_groups = [m.group_id for m in Membership.query.filter_by(user_id=current_user().id).all()]
    if not my_groups:
        return jsonify([])
    rooms = Room.query.filter(Room.group_id.in_(my_groups), Room.active == True).order_by(Room.created_at.desc()).all()
    result = []
    for r in rooms:
        g = db.session.get(Group, r.group_id)
        result.append({
            "id": r.id, "name": r.name, "group_id": r.group_id,
            "group_name": g.name if g else "", "owner_id": r.owner_id
        })
    return jsonify(result)

@app.post("/api/groups/<int:group_id>/rooms")
@login_required
def create_room(group_id):
    if not csrf_required():
        return jsonify({"error": "Invalid CSRF token."}), 403
    if not is_member(current_user().id, group_id):
        return jsonify({"error": "Join the group first."}), 403
    data = request.get_json() or {}
    name = clean_text(data.get("name"), 150) or "Study Room"
    room = Room(group_id=group_id, name=name, owner_id=current_user().id)
    db.session.add(room)
    db.session.commit()
    for m in Membership.query.filter_by(group_id=group_id).all():
        if m.user_id != current_user().id:
            create_notification(m.user_id, "Study room started",
                                f"{current_user().name} started “{name}”. Join now!",
                                "#rooms")
    return jsonify({"message": "Room created.", "room_id": room.id}), 201

@app.post("/api/reports")
@login_required
@limiter.limit("10 per hour")
def report():
    if not csrf_required():
        return jsonify({"error": "Invalid CSRF token."}), 403
    data = request.get_json() or {}
    target_type = clean_text(data.get("target_type"), 50)
    if target_type not in {"user", "status", "post", "room", "project"}:
        return jsonify({"error": "Invalid report target."}), 400
    r = Report(
        reporter_id=current_user().id, target_type=target_type,
        target_id=clean_text(str(data.get("target_id", "")), 100),
        reason=clean_text(data.get("reason"), 100),
        details=clean_text(data.get("details"), 1000)
    )
    db.session.add(r)
    db.session.commit()
    return jsonify({"message": "Report submitted. The team will review it."}), 201

@app.post("/api/block/<int:user_id>")
@login_required
def block_user(user_id):
    if not csrf_required():
        return jsonify({"error": "Invalid CSRF token."}), 403
    if user_id == current_user().id:
        return jsonify({"error": "You cannot block yourself."}), 400
    if not db.session.get(User, user_id):
        return jsonify({"error": "User not found."}), 404
    if not Block.query.filter_by(blocker_id=current_user().id, blocked_id=user_id).first():
        db.session.add(Block(blocker_id=current_user().id, blocked_id=user_id))
        db.session.commit()
    return jsonify({"message": "User blocked."})

# ---------------------------------------------------------
# NOTIFICATIONS + AI
# ---------------------------------------------------------
@app.get("/api/notifications")
@login_required
def get_notifications():
    notes = Notification.query.filter_by(user_id=current_user().id).order_by(Notification.created_at.desc()).limit(30).all()
    return jsonify([{
        "id": n.id, "title": n.title, "body": n.body, "link": n.link,
        "is_read": n.is_read, "created_at": n.created_at.isoformat()
    } for n in notes])

@app.post("/api/notifications/read")
@login_required
def mark_notifications_read():
    if not csrf_required():
        return jsonify({"error": "Invalid CSRF token."}), 403
    Notification.query.filter_by(user_id=current_user().id, is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"message": "Marked as read."})

@app.post("/api/ai/assist")
@login_required
@limiter.limit("20 per hour")
def ai_endpoint():
    if not csrf_required():
        return jsonify({"error": "Invalid CSRF token."}), 403
    data = request.get_json() or {}
    prompt = clean_text(data.get("prompt"), 1000)
    if not prompt:
        return jsonify({"error": "Prompt required."}), 400
    u = current_user()
    context = f"Student: {u.name}, Faculty: {u.faculty}, Course: {u.course}, Skills: {u.skills}"
    answer = ai_assist(prompt, context)
    return jsonify({"answer": answer})

# ---------------------------------------------------------
# WEBRTC SIGNALING
# ---------------------------------------------------------
socket_rooms = {}
socket_room_by_sid = {}
sid_to_user = {}

@socketio.on("connect")
def socket_connect():
    user = current_user()
    if not user:
        return False
    sid_to_user[request.sid] = {"id": user.id, "name": user.name}
    join_room(f"user-{user.id}")

@socketio.on("join_video_room")
def join_video_room(data):
    user = current_user()
    if not user:
        return
    try:
        room_id = int(data.get("room_id"))
    except (TypeError, ValueError):
        emit("room_error", {"message": "Invalid room."})
        return
    room = db.session.get(Room, room_id)
    if not room or not is_member(user.id, room.group_id):
        emit("room_error", {"message": "You cannot join this room."})
        return
    channel = f"video-room-{room_id}"
    existing = list(socket_rooms.get(channel, set()))
    join_room(channel)
    socket_rooms.setdefault(channel, set()).add(request.sid)
    socket_room_by_sid[request.sid] = channel
    emit("existing_peers", {"peers": existing})
    emit("participant_joined", {
        "sid": request.sid, "name": user.name, "user_id": user.id
    }, to=channel, include_self=False)

@socketio.on("signal")
def signal(data):
    if not current_user():
        return
    target = data.get("to")
    if not target:
        return
    if socket_room_by_sid.get(request.sid) != socket_room_by_sid.get(target):
        return
    emit("signal", {"from": request.sid, "data": data.get("data")}, to=target)

@socketio.on("leave_video_room")
@socketio.on("disconnect")
def leave_handler():
    channel = socket_room_by_sid.pop(request.sid, None)
    sid_to_user.pop(request.sid, None)
    if not channel:
        return
    leave_room(channel)
    if channel in socket_rooms:
        socket_rooms[channel].discard(request.sid)
        if not socket_rooms[channel]:
            del socket_rooms[channel]
    emit("participant_left", {"sid": request.sid}, to=channel)

# ---------------------------------------------------------
# INIT
# ---------------------------------------------------------
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_ENV") == "development"
    )
