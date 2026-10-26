# Deploying to PythonAnywhere (free)

A step-by-step guide to get this app running at `https://<your-username>.pythonanywhere.com`.

Why PythonAnywhere: the free tier gives you a **permanent filesystem**, so `attendance.db`
survives restarts and redeploys — unlike hosts with an ephemeral disk (e.g. Render's free tier).

---

## 1. Create the account

1. Go to https://www.pythonanywhere.com and sign up for the **Beginner (free)** plan.
2. Your username becomes your URL: `https://<username>.pythonanywhere.com`.

## 2. Get the code onto PythonAnywhere

Open **Consoles → Bash** and run:

```bash
git clone https://github.com/asinguzashivan6-tech/Attendance-System.git
cd Attendance-System
```

> If `git clone` is blocked, download the repo as a ZIP from GitHub and upload it
> via the **Files** tab, then unzip with `unzip Attendance-System.zip`.

## 3. Install the dependencies

PythonAnywhere's system Python is fine; use a virtualenv:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4. Create your `.env`

```bash
python -c "import secrets; print(secrets.token_hex(32))"
nano .env
```

Put this inside `.env` (paste the generated value):

```
SECRET_KEY=<paste-the-generated-value>
FLASK_DEBUG=False
```

Save with `Ctrl+O`, Enter, then exit with `Ctrl+X`.

## 5. Create the attendance database + first admin

```bash
source venv/bin/activate
python create_admin.py --name "Your Name" --email you@example.com --password "yourpassword"
```

This also creates the database tables.

## 6. Configure the web app

1. Go to the **Web** tab → **Add a new web app**
2. Choose **Manual configuration** (not Flask — manual is more predictable)
3. Choose **Python 3.10** (or the newest available)
4. On the web app page, set:
   - **Source code:** `/home/<username>/Attendance-System`
   - **Working directory:** `/home/<username>/Attendance-System`
   - **Virtualenv:** `/home/<username>/Attendance-System/venv`
5. Click the **WSGI configuration file** link (e.g. `/var/www/<username>_pythonanywhere_com_wsgi.py`)
6. Delete everything in it and paste this (change the path to match your username):

```python
import os
import sys

project_home = "/home/<username>/Attendance-System"
if project_home not in sys.path:
    sys.path.insert(0, project_home)

from app import app as application
```

7. Click **Save**, then go back to the Web tab and click **Reload**.

## 7. Visit your app

Open `https://<username>.pythonanywhere.com` and log in with the admin account from step 5.

---

## Updating the site after you push changes

On PythonAnywhere:

```bash
cd ~/Attendance-System
git pull
```

Then click **Reload** on the Web tab.

## Common problems

| Symptom | Fix |
|---|---|
| `DisallowedHost` / 400 error | Add your domain to `ALLOWED_HOSTS` or set it in the web app's WSGI file |
| `no such table` | The DB wasn't created — rerun step 5 |
| `ModuleNotFoundError: No module named 'flask'` | Virtualenv path on the Web tab is wrong |
| Changes don't appear | You forgot to click **Reload** |
| Emails/QR images missing | Check uploads still exist under `static/uploads/` |
| Free app "hit the 3rd CPU second" | Free tier is slow for heavy use; upgrade or optimize |

## Notes

- Free PythonAnywhere apps sleep after inactivity; the first visit may take a few seconds.
- Free tier allows outbound requests only to a whitelist (GitHub and PyPI are included).
- Keep `.env` and `instance/attendance.db` out of git — they are already in `.gitignore`.
