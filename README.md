# QR Attendance System

A Flask web app that marks student attendance by scanning a rotating QR code shown by the teacher. Built for a class/lecture setting where students use their phones.

## Features

- **Three roles:** admin, teacher, student
- **Rotating QR codes:** tokens are HMAC-signed and change every few seconds, so a screenshot can't be reused
- **Device binding:** a student's account is tied to the first device that marks attendance
- **Live session view:** teacher sees attendance appear in real time
- **Reports:** export attendance to Excel
- **Admin tools:** manage users, classes, and app settings (including logo upload)

## Tech stack

| Layer | Tech |
|-------|------|
| Backend | Flask 3, Flask-SQLAlchemy |
| Database | SQLite |
| QR | `qrcode` (Python) + `qrcodejs` (browser) |
| Auth | Werkzeug password hashing, session cookies |
| Reports | openpyxl |

## Local setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your .env file (copy the example and set a real secret)
copy .env.example .env       # Windows
# cp .env.example .env       # macOS / Linux
```

Generate a strong secret key for `.env`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

```bash
# 4. Create the first admin account
python create_admin.py --name "Your Name" --email you@example.com --password "yourpassword"

# 5. Run the app
python app.py
```

Open `http://127.0.0.1:5000`. To use it from phones on the same Wi-Fi, use the "For phones" address printed in the console.

## Project structure

```
app.py              Main Flask app: models, routes, QR/token logic
create_admin.py     CLI to create the first admin
requirements.txt    Python dependencies
templates/          Jinja2 pages (dashboards, scan, live session, reports)
static/css/         Stylesheet
static/qr/          Generated QR images
static/uploads/     Uploaded logos
utils/tokens.py     HMAC token generation/verification
utils/validators.py Input validation
instance/           SQLite database (gitignored)
```

## Security notes

- `.env`, the database, and uploads are **gitignored** — never commit real attendance data.
- Set a real `SECRET_KEY` in production. The code falls back to a dev key only for local use.
- `FLASK_DEBUG` should be `False` on any public deployment.

## Hosting

GitHub Pages **cannot** host this app — it only serves static files, and this needs a Python server.

When you're ready to deploy, suitable options are Render, PythonAnywhere, Railway, or Fly.io. Things to handle at that point:

1. Add a production WSGI server (`gunicorn`) to the dependencies.
2. Keep the SQLite file on persistent storage, or move to a hosted Postgres database.
3. Set `SECRET_KEY` and `FLASK_DEBUG=False` as environment variables on the host.
