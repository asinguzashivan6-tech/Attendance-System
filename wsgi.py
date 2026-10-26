"""WSGI entry point for PythonAnywhere (and gunicorn).

On PythonAnywhere:
  1. Web tab -> Add a new web app -> Manual configuration -> Python 3.10
  2. Set "Source code" to the folder containing app.py
  3. Set "Virtualenv" to the venv you created, e.g. /home/<user>/Attendance-System/venv
  4. Open the WSGI configuration file link, delete its contents,
     and paste the lines below (adjust project_home if needed).
  5. Click Reload.

For gunicorn:  gunicorn wsgi:application
"""

import os
import sys

# Folder that contains app.py (this file's own folder).
project_home = os.path.dirname(os.path.abspath(__file__))
if project_home not in sys.path:
    sys.path.insert(0, project_home)

from app import app as application  # noqa: E402
