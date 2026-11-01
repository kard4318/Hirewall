# Test-wide settings: quarantine records stay in memory and the security model is off unless a test enables it
import os

os.environ["SECURITY_QUARANTINE_FILE"] = ""
os.environ.setdefault("SECURITY_MODEL_MODE", "off")
