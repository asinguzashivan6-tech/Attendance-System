import hmac
import hashlib
import base64
import json
import time
import uuid
import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv('SECRET_KEY', 'devsecretkey')

def generate_token(session_id):
    """Generate a signed, short-lived token for a session"""
    payload = {
        "sid": session_id,
        "ts": int(time.time()),
        "n": uuid.uuid4().hex[:10]
    }
    payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    sig = hmac.new(SECRET_KEY.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()
    token_str = base64.urlsafe_b64encode(payload_bytes + b'.' + sig.encode('utf-8')).decode('utf-8').rstrip('=')
    return token_str

def verify_token(token):
    """Verify token signature and age (max 30 seconds)"""
    try:
        padding = '=' * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(token + padding)
        if b'.' not in decoded:
            return {"valid": False, "reason": "Invalid token format"}
        payload_bytes, sig_bytes = decoded.split(b'.', 1)
        sig_given = sig_bytes.decode('utf-8')
        sig_calc = hmac.new(SECRET_KEY.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig_given, sig_calc):
            return {"valid": False, "reason": "Invalid signature"}
        payload = json.loads(payload_bytes.decode('utf-8'))
        session_id = payload.get('sid')
        ts = payload.get('ts')
        if not session_id or not ts:
            return {"valid": False, "reason": "Missing fields"}
        age = int(time.time()) - int(ts)
        if age > 30:
            return {"valid": False, "reason": "QR expired"}
        if age < 0:
            return {"valid": False, "reason": "Invalid timestamp"}
        return {"valid": True, "session_id": session_id, "age": age}
    except Exception as e:
        return {"valid": False, "reason": "Token verification failed"}