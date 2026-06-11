"""Generate a VAPID keypair for Web Push.

Prints two base64url (unpadded) values to paste into the backend ``.env``:

    VAPID_PUBLIC_KEY=...   # also the browser's applicationServerKey
    VAPID_PRIVATE_KEY=...

Run once per environment; keep the private key secret. The public key is what
the frontend fetches from ``/api/push/vapid-public-key`` to subscribe.

Requires ``cryptography`` (pulled in by ``pywebpush``), so install deps first:

    pip install -r requirements.txt
    python scripts/gen_vapid_keys.py
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def main() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )  # 65 bytes: 0x04 || X || Y
    print("VAPID_PUBLIC_KEY=" + _b64url(public_raw))
    print("VAPID_PRIVATE_KEY=" + _b64url(private_raw))


if __name__ == "__main__":
    main()
