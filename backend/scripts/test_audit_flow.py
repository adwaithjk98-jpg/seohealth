"""End-to-end test: POST /api/audits, then read the SSE stream.

Usage (server must already be running on :8000):
    .venv/bin/python -m scripts.test_audit_flow [BUSINESS_ID]

If BUSINESS_ID is omitted, seeds a demo business first.
Uses only the standard library — no extra deps.
"""
import json
import sys
import urllib.request

BASE_URL = "http://127.0.0.1:8000"


def post_audit(business_id: int) -> dict:
    body = json.dumps({"business_id": business_id, "trigger": "manual"}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/api/audits",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def stream_audit(audit_id: int) -> None:
    url = f"{BASE_URL}/api/audits/{audit_id}/stream"
    req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    print(f"-> Streaming {url}\n")
    event_type = None
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\n").rstrip("\r")
            if line == "":
                event_type = None
                continue
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_str = line[len("data:"):].strip()
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    data = data_str
                print(f"[{event_type or 'message'}] {json.dumps(data, indent=2)}")
                if event_type in ("audit_completed", "audit_failed"):
                    return


def main() -> None:
    if len(sys.argv) > 1:
        business_id = int(sys.argv[1])
    else:
        from scripts.seed_demo_business import main as seed
        business_id = seed()
        print(f"-> Seeded business id={business_id}\n")

    resp = post_audit(business_id)
    print(f"-> POST /api/audits -> {json.dumps(resp, indent=2)}\n")
    stream_audit(resp["audit_id"])


if __name__ == "__main__":
    main()
