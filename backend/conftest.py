# Test-wide settings: quarantine records stay in memory and the security model is off unless a test enables it
import os
import tempfile

os.environ["SECURITY_QUARANTINE_FILE"] = ""
os.environ.setdefault("SECURITY_MODEL_MODE", "off")
# Anything a test does not point elsewhere (audit log, users file, queues) goes to a throwaway folder, never the repo.
_RUNTIME = tempfile.mkdtemp(prefix="hirewall-tests-")
os.environ["HIREWALL_RUNTIME_DIR"] = _RUNTIME
os.environ["HIREWALL_USERS_FILE"] = os.path.join(_RUNTIME, "users.json")
