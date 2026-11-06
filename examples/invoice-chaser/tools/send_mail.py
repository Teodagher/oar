#!/usr/bin/env python3
"""Send one email through the Gmail API with the token file the host wrote.

  send_mail.py --to ADDRESS --subject TEXT --body-file PATH [--cc ADDRESS]

The token file is `.secrets/gmail-token.json` in the agent's folder (a secret file target,
rendered by the host from the vault item `Gmail`). This example only checks the arguments and
the token file; a real agent would call the Gmail API here.
"""
import argparse
import json
import sys
from pathlib import Path

TOKEN = Path(__file__).resolve().parent.parent / ".secrets" / "gmail-token.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--cc")
    args = ap.parse_args()
    if not TOKEN.exists():
        print("The Gmail login is missing: add the vault item 'Gmail' and restart the agent.", file=sys.stderr)
        return 1
    token = json.loads(TOKEN.read_text())
    if not token.get("refresh_token"):
        print("The Gmail login has no refresh_token field.", file=sys.stderr)
        return 1
    body = Path(args.body_file).read_text()
    print(f"would send to {args.to} (cc {args.cc or '-'}): {args.subject} ({len(body)} characters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
