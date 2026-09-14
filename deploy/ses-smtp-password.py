#!/usr/bin/env python3
"""Derive an SES SMTP password from an IAM secret access key.

SES SMTP credentials are not a separate secret: the username is the IAM access
key id, and the password is an HMAC derivation of the secret access key for a
specific region. The console's "Create SMTP credentials" button does exactly
this. Doing it here means the IAM user can be created with the CLI, scoped to
one identity, and the derivation repeated for another region without minting a
second credential.

    python3 deploy/ses-smtp-password.py <secret-access-key> [region]

Algorithm: docs.aws.amazon.com/ses/latest/dg/smtp-credentials.html
"""

import base64
import hashlib
import hmac
import sys

# Fixed by the algorithm; not a real date.
DATE = "11111111"
SERVICE = "ses"
TERMINAL = "aws4_request"
MESSAGE = "SendRawEmail"
VERSION = 0x04


def sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def smtp_password(secret_access_key: str, region: str) -> str:
    sig = sign(("AWS4" + secret_access_key).encode("utf-8"), DATE)
    for part in (region, SERVICE, TERMINAL, MESSAGE):
        sig = sign(sig, part)
    return base64.b64encode(bytes([VERSION]) + sig).decode("utf-8")


if __name__ == "__main__":
    if not 2 <= len(sys.argv) <= 3:
        sys.exit(__doc__)
    print(smtp_password(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "us-east-1"))
