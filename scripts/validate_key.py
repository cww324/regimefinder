import os
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    key = settings.api_secret.replace("\\n", "\n") if settings.api_secret else ""
    if not key:
        print("COINBASE_PRIVATE_KEY not set")
        return
    try:
        load_pem_private_key(key.encode("utf-8"), password=None)
        print("PEM private key: OK")
    except Exception as e:
        print(f"PEM private key: ERROR -> {e}")


if __name__ == "__main__":
    main()
