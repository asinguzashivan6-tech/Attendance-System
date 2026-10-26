import os
import re
import socket
import hashlib
import io
import base64
import csv
from datetime import datetime, timedelta
from io import BytesIO

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import qrcode

from utils.tokens import generate_token, verify_token
from utils.validators import validate_name, validate_email, validate_password

# Load environment variables
load_dotenv()

# Initialize app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'devsecretkey')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2 MB max upload

# Initialize database
db = SQLAlchemy(app)

# -------------------- MODELS --------------------

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # admin | teacher | student
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    classes = db.relationship('Class', backref='teacher', lazy=True)
    sessions = db.relationship('Session', backref='teacher', lazy=True)
    attendances = db.relationship('Attendance', backref='student', lazy=True)
    devices = db.relationship('Device', backref='student', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Class(db.Model):
    __tablename__ = 'classes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    course_code = db.Column(db.String(50), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sessions = db.relationship('Session', backref='class_', lazy=True)


class Session(db.Model):
    __tablename__ = 'sessions'
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(10), default='active')  # active | ended
    grace_minutes = db.Column(db.Integer, default=5)
    start_at = db.Column(db.DateTime, default=datetime.utcnow)
    end_at = db.Column(db.DateTime, nullable=True)
    geofence_lat = db.Column(db.Float, nullable=True)
    geofence_lng = db.Column(db.Float, nullable=True)
    geofence_radius = db.Column(db.Float, nullable=True)  # meters
    require_device_bind = db.Column(db.Boolean, default=False)

    attendances = db.relationship('Attendance', backref='session', lazy=True)


class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(10), default='present')  # present | late
    marked_at = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(50), nullable=True)
    device_hash = db.Column(db.String(64), nullable=True)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)


class Device(db.Model):
    __tablename__ = 'devices'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    device_hash = db.Column(db.String(64), nullable=False)
    user_agent = db.Column(db.String(255), nullable=True)
    first_used_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, default=datetime.utcnow)


class Setting(db.Model):
    """Single-row table holding institution branding (id = 1)."""
    __tablename__ = 'settings'
    id = db.Column(db.Integer, primary_key=True)
    institution_name = db.Column(db.String(150), nullable=False, default='QR Attendance System')
    short_name = db.Column(db.String(50), nullable=False, default='QR Attendance')
    logo_url = db.Column(db.String(255), nullable=True)
    primary_color = db.Column(db.String(7), nullable=False, default='#0d6efd')


# -------------------- UTILS --------------------

DEFAULT_BRAND = {
    'institution_name': 'QR Attendance System',
    'short_name': 'QR Attendance',
    'logo_url': None,
    'primary_color': '#0d6efd',
}


def ensure_settings():
    if db.session.get(Setting, 1) is None:
        db.session.add(Setting(id=1))
        db.session.commit()


def get_brand():
    s = db.session.get(Setting, 1)
    if s is None:
        return dict(DEFAULT_BRAND)
    return {
        'institution_name': s.institution_name or DEFAULT_BRAND['institution_name'],
        'short_name': s.short_name or DEFAULT_BRAND['short_name'],
        'logo_url': s.logo_url,
        'primary_color': s.primary_color or DEFAULT_BRAND['primary_color'],
    }


@app.context_processor
def inject_brand():
    return {'brand': get_brand()}

def get_device_hash():
    ua = request.headers.get('User-Agent', '')
    raw = f"{ua}-{request.remote_addr}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return db.session.get(User, uid)


PUBLIC_ENDPOINTS = {
    'static', 'index', 'login', 'logout', 'register', 'student_register',
    'admin_login', 'teacher_login', 'student_login',
}


@app.before_request
def enforce_role_access():
    """Central gatekeeper: blocks any role from touching another interface."""
    if request.endpoint is None or request.endpoint in PUBLIC_ENDPOINTS:
        return None

    if 'user_id' not in session:
        flash('Please login first')
        return redirect(url_for('login'))

    user = current_user()
    if not user or not user.is_active:
        session.clear()
        flash('Your account is inactive or no longer exists')
        return redirect(url_for('login'))

    # keep session in sync with the database
    session['role'] = user.role
    session['name'] = user.name

    path = request.path
    if path.startswith('/admin') and user.role != 'admin':
        return render_template('forbidden.html'), 403
    if path.startswith('/teacher') and user.role != 'teacher':
        return render_template('forbidden.html'), 403
    if path.startswith('/student') and user.role != 'student':
        return render_template('forbidden.html'), 403
    if path == '/scan' and user.role != 'student':
        return render_template('forbidden.html'), 403
    return None


# -------------------- ROUTES --------------------

@app.route('/')
def index():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            if user.role == 'teacher':
                return redirect(url_for('teacher_dashboard'))
            if user.role == 'student':
                return redirect(url_for('student_dashboard'))
    return render_template('index.html')


@app.route('/register')
def register():
    return redirect(url_for('student_register'))


@app.route('/student/register', methods=['GET', 'POST'])
def student_register():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''

        error = (validate_name(name) or validate_email(email)
                 or validate_password(password))
        if error:
            flash(error)
            return render_template('register.html', form=request.form)

        if User.query.filter_by(email=email).first():
            flash('That email is already registered. Please login instead.')
            return render_template('register.html', form=request.form)

        user = User(name=name, email=email, role='student', is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please login with your student link.')
        return redirect(url_for('student_login'))

    return render_template('register.html', form={})


def do_login(required_role):
    """Shared login handler. Rejects accounts from a different role portal."""
    if 'user_id' in session:
        if session.get('role') != required_role:
            flash(f'You are logged in as {session.get("role")}. '
                  'Log out first to use a different portal.')
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''

        if not email or not password:
            flash('Email and password are required')
            return render_template('login.html', portal_role=required_role)

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash('Invalid email or password')
            return render_template('login.html', portal_role=required_role)

        if not user.is_active:
            flash('This account has been disabled. Contact the administrator.')
            return render_template('login.html', portal_role=required_role)

        if user.role != required_role:
            flash('That account does not have access to this portal. Use its own login link.')
            return render_template('login.html', portal_role=required_role)

        session.clear()
        session['user_id'] = user.id
        session['name'] = user.name
        session['role'] = user.role
        flash(f'Welcome, {user.name}!')
        return redirect(url_for('index'))

    return render_template('login.html', portal_role=required_role)


@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('portal.html')


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    return do_login('admin')


@app.route('/teacher/login', methods=['GET', 'POST'])
def teacher_login():
    return do_login('teacher')


@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    return do_login('student')


@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully')
    return redirect(url_for('index'))


@app.route('/teacher/dashboard')
def teacher_dashboard():
    if 'user_id' not in session or session['role'] != 'teacher':
        flash('Access denied. Login as teacher')
        return redirect(url_for('login'))
    teacher_id = session['user_id']
    classes = Class.query.filter_by(teacher_id=teacher_id).order_by(Class.created_at.desc()).all()
    return render_template('teacher_dashboard.html', classes=classes)


@app.route('/teacher/class/create', methods=['POST'])
def create_class():
    if 'user_id' not in session or session['role'] != 'teacher':
        flash('Access denied')
        return redirect(url_for('login'))

    name = request.form.get('name')
    course_code = request.form.get('course_code')

    if not name or not course_code:
        flash('Class name and course code are required')
        return redirect(url_for('teacher_dashboard'))

    new_class = Class(name=name, course_code=course_code, teacher_id=session['user_id'])
    db.session.add(new_class)
    db.session.commit()
    flash('Class created successfully')
    return redirect(url_for('teacher_dashboard'))


@app.route('/teacher/class/<int:class_id>')
def class_view(class_id):
    if 'user_id' not in session or session['role'] != 'teacher':
        flash('Access denied')
        return redirect(url_for('login'))

    cls = Class.query.get_or_404(class_id)
    if cls.teacher_id != session['user_id']:
        flash('Not authorized to view this class')
        return redirect(url_for('teacher_dashboard'))

    sessions = Session.query.filter_by(class_id=class_id).order_by(Session.start_at.desc()).all()
    return render_template('class_view.html', cls=cls, sessions=sessions)

   
@app.route('/teacher/class/<int:class_id>/session/start', methods=['POST'])
def start_session(class_id):
    if 'user_id' not in session or session['role'] != 'teacher':
        flash('Access denied')
        return redirect(url_for('login'))

    cls = Class.query.get_or_404(class_id)
    if cls.teacher_id != session['user_id']:
        flash('Not authorized')
        return redirect(url_for('teacher_dashboard'))

    try:
        grace = int(request.form.get('grace_minutes') or 5)
    except ValueError:
        grace = 5

    if grace < 0:
        grace = 0
    if grace > 60:
        grace = 60

    new_session = Session(
        class_id=class_id,
        teacher_id=session['user_id'],
        status='active',
        grace_minutes=grace
    )
    db.session.add(new_session)
    db.session.commit()

    flash('Session started successfully')
    return redirect(url_for('live_session', session_id=new_session.id))


@app.route('/teacher/session/<int:session_id>/live')
def live_session(session_id):
    if 'user_id' not in session or session['role'] != 'teacher':
        flash('Access denied')
        return redirect(url_for('login'))

    sess = Session.query.get_or_404(session_id)
    if sess.teacher_id != session['user_id']:
        flash('Not authorized')
        return redirect(url_for('teacher_dashboard'))

    cls = sess.class_
    return render_template('live_session.html', sess=sess, cls=cls)


@app.route('/teacher/session/<int:session_id>/token')
def session_token(session_id):
    if 'user_id' not in session or session['role'] != 'teacher':
        return jsonify({'error': 'unauthorized'}), 403

    sess = Session.query.get_or_404(session_id)
    if sess.teacher_id != session['user_id']:
        return jsonify({'error': 'forbidden'}), 403

    if sess.status != 'active':
        return jsonify({'error': 'session_ended'}), 400

    token = generate_token(sess.id)
    return jsonify({'token': token})



@app.route('/teacher/session/<int:session_id>/attendees')
def session_attendees(session_id):
    if 'user_id' not in session or session['role'] != 'teacher':
        return jsonify({'error': 'unauthorized'}), 403

    sess = Session.query.get_or_404(session_id)
    if sess.teacher_id != session['user_id']:
        return jsonify({'error': 'forbidden'}), 403

    attendees = (Attendance.query
                 .filter_by(session_id=sess.id)
                 .join(User, Attendance.student_id == User.id)
                 .order_by(Attendance.marked_at.desc())
                 .all())

    data = []
    for a in attendees:
        data.append({
            'name': a.student.name,
            'email': a.student.email,
            'status': a.status,
            'time': a.marked_at.strftime('%H:%M:%S')
        })
    return jsonify({'attendees': data})


@app.route('/teacher/session/<int:session_id>/end', methods=['POST'])
def end_session(session_id):
    if 'user_id' not in session or session['role'] != 'teacher':
        flash('Access denied')
        return redirect(url_for('login'))

    sess = Session.query.get_or_404(session_id)
    if sess.teacher_id != session['user_id']:
        flash('Not authorized')
        return redirect(url_for('teacher_dashboard'))

    if sess.status == 'active':
        sess.status = 'ended'
        sess.end_at = datetime.utcnow()
        db.session.commit()
        flash('Session ended')
    else:
        flash('Session already ended')

    return redirect(url_for('class_view', class_id=sess.class_id))


@app.route('/scan', methods=['GET', 'POST'])
def scan():
    token = request.args.get('token') or request.form.get('token')
    result_msg = None
    result_class = 'alert-info'

    if request.method == 'POST' or token:
        if 'user_id' not in session or session['role'] != 'student':
            flash('You must login as a student to mark attendance')
            return redirect(url_for('login'))

        if not token:
            flash('No token provided. Scan the QR again.')
            return redirect(url_for('scan'))

        v = verify_token(token)
        if not v.get('valid'):
            flash(f'Attendance failed: {v.get("reason")}')
            return render_template('scan.html', token=token, result_msg=v.get("reason"), result_class='alert-danger')

        session_id = v.get('session_id')
        sess = Session.query.get(session_id)
        if not sess:
            flash('Invalid session')
            return render_template('scan.html', token=token, result_msg='Invalid session', result_class='alert-danger')

        if sess.status != 'active':
            flash('This session has ended. Attendance not allowed.')
            return render_template('scan.html', token=token, result_msg='Session closed', result_class='alert-danger')

        student_id = session['user_id']
        existing = Attendance.query.filter_by(session_id=sess.id, student_id=student_id).first()
        if existing:
            flash('You have already checked in for this session.')
            return render_template('scan.html', token=token, result_msg='Already checked in', result_class='alert-warning')

        now = datetime.utcnow()
        grace = timedelta(minutes=sess.grace_minutes)
        start = sess.start_at
        status = 'late' if now > start + grace else 'present'

        dh = get_device_hash()
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()

        att = Attendance(session_id=sess.id, student_id=student_id, status=status, marked_at=now, ip_address=ip, device_hash=dh)
        db.session.add(att)
        db.session.commit()

        msg = f'Marked as {status.upper()} for {sess.class_.name} ({sess.class_.course_code})'
        flash(msg)
        return render_template('scan.html', token=token, result_msg=msg, result_class='alert-success')

    return render_template('scan.html', token=token)


@app.route('/student/history')
def student_history():
    if 'user_id' not in session or session['role'] != 'student':
        flash('Access denied. Login as student')
        return redirect(url_for('login'))

    student_id = session['user_id']
    records = (Attendance.query
               .filter_by(student_id=student_id)
               .join(Session)
               .join(Class)
               .order_by(Attendance.marked_at.desc())
               .all())
    return render_template('student_history.html', records=records)


@app.route('/teacher/class/<int:class_id>/report')
def attendance_report(class_id):
    if 'user_id' not in session or session['role'] != 'teacher':
        flash('Access denied')
        return redirect(url_for('login'))

    cls = Class.query.get_or_404(class_id)
    if cls.teacher_id != session['user_id']:
        flash('Not authorized')
        return redirect(url_for('teacher_dashboard'))

    session_id_filter = request.args.get('session_id', type=int)
    sessions_list = Session.query.filter_by(class_id=class_id).order_by(Session.start_at.desc()).all()

    query = (Attendance.query
             .join(Session)
             .filter(Session.class_id == class_id)
             .join(User)
             .order_by(Attendance.marked_at.asc()))

    if session_id_filter:
        query = query.filter(Attendance.session_id == session_id_filter)

    records = query.all()
    return render_template('report.html', cls=cls, records=records, sessions_list=sessions_list, session_id_filter=session_id_filter)


@app.route('/teacher/class/<int:class_id>/export.csv')
def export_csv(class_id):
    if 'user_id' not in session or session['role'] != 'teacher':
        return redirect(url_for('login'))

    cls = Class.query.get_or_404(class_id)
    if cls.teacher_id != session['user_id']:
        return redirect(url_for('teacher_dashboard'))

    session_id_filter = request.args.get('session_id', type=int)

    query = (Attendance.query
             .join(Session)
             .filter(Session.class_id == class_id)
             .join(User)
             .order_by(Attendance.marked_at.asc()))

    if session_id_filter:
        query = query.filter(Attendance.session_id == session_id_filter)

    records = query.all()

    si = BytesIO()
    writer = csv.writer(si)
    writer.writerow(['Class', 'Course Code', 'Session Start', 'Student Name', 'Student Email', 'Status', 'Marked At'])

    for r in records:
        writer.writerow([r.session.class_.name, r.session.class_.course_code, r.session.start_at.strftime('%Y-%m-%d %H:%M:%S'),
                         r.student.name, r.student.email, r.status, r.marked_at.strftime('%Y-%m-%d %H:%M:%S')])

    si.seek(0)
    return Response(si.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=attendance_{cls.course_code}.csv'})


@app.route('/teacher/class/<int:class_id>/export.xlsx')
def export_excel(class_id):
    if 'user_id' not in session or session['role'] != 'teacher':
        return redirect(url_for('login'))

    cls = Class.query.get_or_404(class_id)
    if cls.teacher_id != session['user_id']:
        return redirect(url_for('teacher_dashboard'))

    from openpyxl import Workbook
    session_id_filter = request.args.get('session_id', type=int)

    query = (Attendance.query
             .join(Session)
             .filter(Session.class_id == class_id)
             .join(User)
             .order_by(Attendance.marked_at.asc()))

    if session_id_filter:
        query = query.filter(Attendance.session_id == session_id_filter)

    records = query.all()

    wb = Workbook()
    ws = wb.active
    ws.append(['Class', 'Course Code', 'Session Start', 'Student Name', 'Student Email', 'Status', 'Marked At'])
    for r in records:
        ws.append([r.session.class_.name, r.session.class_.course_code, r.session.start_at.strftime('%Y-%m-%d %H:%M:%S'),
                   r.student.name, r.student.email, r.status, r.marked_at.strftime('%Y-%m-%d %H:%M:%S')])

    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return send_file(out, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=f'attendance_{cls.course_code}.xlsx')

@app.route('/student/dashboard')
def student_dashboard():
    if 'user_id' not in session or session['role'] != 'student':
        flash('Access denied. Login as student')
        return redirect(url_for('login'))
    return render_template('student_dashboard.html')


# -------------------- ADMIN --------------------

@app.route('/admin/dashboard')
def admin_dashboard():
    stats = {
        'teachers': User.query.filter_by(role='teacher').count(),
        'students': User.query.filter_by(role='student').count(),
        'classes': Class.query.count(),
        'sessions': Session.query.count(),
        'attendance': Attendance.query.count(),
        'disabled': User.query.filter_by(is_active=False).count(),
    }
    recent_attendance = (Attendance.query
                         .join(User, Attendance.student_id == User.id)
                         .order_by(Attendance.marked_at.desc())
                         .limit(10).all())
    recent_sessions = Session.query.order_by(Session.start_at.desc()).limit(10).all()
    return render_template('admin_dashboard.html', stats=stats,
                           recent_attendance=recent_attendance,
                           recent_sessions=recent_sessions)


@app.route('/admin/users')
def admin_users():
    role_filter = request.args.get('role', '')
    search = request.args.get('q', '').strip()

    query = User.query
    if role_filter in ('admin', 'teacher', 'student'):
        query = query.filter_by(role=role_filter)
    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(User.name.ilike(like), User.email.ilike(like)))

    users = query.order_by(User.role.asc(), User.name.asc()).all()
    return render_template('admin_users.html', users=users,
                           role_filter=role_filter, search=search)


@app.route('/admin/users/create', methods=['POST'])
def admin_create_user():
    name = (request.form.get('name') or '').strip()
    email = (request.form.get('email') or '').strip().lower()
    password = request.form.get('password') or ''
    role = request.form.get('role') or ''

    if not all([name, email, password, role]):
        flash('All fields are required')
        return redirect(url_for('admin_users'))

    if role not in ('admin', 'teacher', 'student'):
        flash('Invalid role')
        return redirect(url_for('admin_users'))

    error = (validate_name(name) or validate_email(email)
             or validate_password(password))
    if error:
        flash(error)
        return redirect(url_for('admin_users'))

    if User.query.filter_by(email=email).first():
        flash('That email is already registered')
        return redirect(url_for('admin_users'))

    user = User(name=name, email=email, role=role, is_active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f'{role.capitalize()} account created: {email}')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:user_id>/toggle', methods=['POST'])
def admin_toggle_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found')
        return redirect(url_for('admin_users'))

    if user.id == session.get('user_id'):
        flash('You cannot disable your own account')
        return redirect(url_for('admin_users'))

    user.is_active = not user.is_active
    db.session.commit()
    flash(f'{user.name} is now {"active" if user.is_active else "disabled"}')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:user_id>/password', methods=['POST'])
def admin_reset_password(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found')
        return redirect(url_for('admin_users'))

    new_password = request.form.get('password') or ''
    error = validate_password(new_password)
    if error:
        flash(error)
        return redirect(url_for('admin_users'))

    user.set_password(new_password)
    db.session.commit()
    flash(f'Password reset for {user.name}')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
def admin_delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found')
        return redirect(url_for('admin_users'))

    if user.id == session.get('user_id'):
        flash('You cannot delete your own account')
        return redirect(url_for('admin_users'))

    if user.role == 'teacher' and (user.classes or user.sessions):
        flash('Cannot delete a teacher who owns classes or sessions. Disable the account instead.')
        return redirect(url_for('admin_users'))

    if user.role == 'student' and user.attendances:
        flash('Cannot delete a student with attendance records. Disable the account instead.')
        return redirect(url_for('admin_users'))

    db.session.delete(user)
    db.session.commit()
    flash(f'User deleted: {user.email}')
    return redirect(url_for('admin_users'))


@app.route('/admin/classes')
def admin_classes():
    classes = Class.query.order_by(Class.created_at.desc()).all()
    return render_template('admin_classes.html', classes=classes)


@app.route('/admin/attendance')
def admin_attendance():
    class_id = request.args.get('class_id', type=int)
    date_str = request.args.get('date', '').strip()
    search = request.args.get('q', '').strip()

    query = (Attendance.query
             .join(Session, Attendance.session_id == Session.id)
             .join(Class, Session.class_id == Class.id)
             .join(User, Attendance.student_id == User.id))

    if class_id:
        query = query.filter(Class.id == class_id)
    if date_str:
        try:
            start = datetime.strptime(date_str, '%Y-%m-%d')
            query = query.filter(Attendance.marked_at >= start,
                                 Attendance.marked_at < start + timedelta(days=1))
        except ValueError:
            flash('Invalid date format, use YYYY-MM-DD')
    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(User.name.ilike(like), User.email.ilike(like)))

    records = query.order_by(Attendance.marked_at.desc()).all()
    classes = Class.query.order_by(Class.name.asc()).all()
    return render_template('admin_attendance.html', records=records, classes=classes,
                           class_id=class_id, date_str=date_str, search=search)


@app.route('/admin/attendance/export.csv')
def admin_export_csv():
    class_id = request.args.get('class_id', type=int)
    date_str = request.args.get('date', '').strip()

    query = (Attendance.query
             .join(Session, Attendance.session_id == Session.id)
             .join(Class, Session.class_id == Class.id)
             .join(User, Attendance.student_id == User.id))

    if class_id:
        query = query.filter(Class.id == class_id)
    if date_str:
        try:
            start = datetime.strptime(date_str, '%Y-%m-%d')
            query = query.filter(Attendance.marked_at >= start,
                                 Attendance.marked_at < start + timedelta(days=1))
        except ValueError:
            pass

    records = query.order_by(Attendance.marked_at.asc()).all()

    si = BytesIO()
    writer = csv.writer(si)
    writer.writerow(['Class', 'Course Code', 'Teacher', 'Session Start', 'Student Name',
                     'Student Email', 'Status', 'Marked At'])
    for r in records:
        writer.writerow([
            r.session.class_.name,
            r.session.class_.course_code,
            r.session.teacher.name if r.session.teacher else '-',
            r.session.start_at.strftime('%Y-%m-%d %H:%M:%S'),
            r.student.name,
            r.student.email,
            r.status,
            r.marked_at.strftime('%Y-%m-%d %H:%M:%S'),
        ])

    si.seek(0)
    return Response(si.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=all_attendance.csv'})


ALLOWED_LOGO_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
COLOR_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')


@app.route('/admin/settings', methods=['GET', 'POST'])
def admin_settings():
    settings = db.session.get(Setting, 1)
    if settings is None:
        settings = Setting(id=1)
        db.session.add(settings)
        db.session.commit()

    if request.method == 'POST':
        institution_name = (request.form.get('institution_name') or '').strip()
        short_name = (request.form.get('short_name') or '').strip()
        primary_color = (request.form.get('primary_color') or '').strip()

        if len(institution_name) < 2:
            flash('Institution name must be at least 2 characters')
            return redirect(url_for('admin_settings'))

        settings.institution_name = institution_name[:150]
        settings.short_name = (short_name or institution_name)[:50]
        if COLOR_RE.match(primary_color):
            settings.primary_color = primary_color

        if request.form.get('remove_logo'):
            settings.logo_url = None

        logo = request.files.get('logo')
        if logo and logo.filename:
            ext = logo.filename.rsplit('.', 1)[-1].lower() if '.' in logo.filename else ''
            if ext not in ALLOWED_LOGO_EXT:
                flash('Logo must be a PNG, JPG, GIF or WEBP image')
                return redirect(url_for('admin_settings'))
            upload_dir = os.path.join(app.static_folder, 'uploads')
            os.makedirs(upload_dir, exist_ok=True)
            filename = f'logo_{datetime.utcnow().strftime("%Y%m%d%H%M%S")}.{ext}'
            logo.save(os.path.join(upload_dir, filename))
            settings.logo_url = url_for('static', filename=f'uploads/{filename}')

        db.session.commit()
        flash('Institution branding saved successfully')
        return redirect(url_for('admin_settings'))

    return render_template('admin_settings.html', settings=settings)


@app.errorhandler(413)
def file_too_large(error):
    flash('That file is too large. Maximum upload size is 2 MB.')
    return redirect(url_for('admin_settings'))


# -------------------- MAIN --------------------

def get_local_ip():
    """Best-effort LAN IP of this machine (no internet needed)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


def initialize_app():
    """Create tables and default settings. Safe to call repeatedly."""
    with app.app_context():
        db.create_all()
        ensure_settings()


# Run on import so hosted WSGI servers (PythonAnywhere, gunicorn) get a ready database.
initialize_app()


if __name__ == '__main__':
    port = int(os.getenv('PORT', '5000'))
    ip = get_local_ip()
    print("=" * 60)
    print("  QR Attendance System is running")
    print(f"  On this PC:   http://127.0.0.1:{port}")
    print(f"  For phones:   http://{ip}:{port}")
    print("  Phones/other devices must use the 'For phones' address")
    print("  Keep this window open. Press Ctrl+C to stop.")
    print("=" * 60)
    debug = os.getenv('FLASK_DEBUG', 'False').strip().lower() == 'true'
    app.run(debug=debug, host='0.0.0.0', port=port)


