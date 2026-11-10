"""Container health check: GET /healthz/ with the Host header Django expects."""
import os
import sys
import urllib.request

host = os.environ.get("ALLOWED_HOSTS", "localhost").split(",")[0].strip()
request = urllib.request.Request("http://127.0.0.1:8000/healthz/", headers={"Host": host})
try:
    sys.exit(0 if urllib.request.urlopen(request, timeout=4).status == 200 else 1)
except Exception:
    sys.exit(1)
