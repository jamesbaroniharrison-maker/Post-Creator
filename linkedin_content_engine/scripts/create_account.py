"""Create (or reset) the single dashboard login account.

Single-user system - no self-service registration route is wired up by design (see
CLAUDE.md), so this is how the one account gets created: directly, via this script,
not through a web form.

Usage (from linkedin_content_engine/, with the venv active):
    python -m scripts.create_account --username you --password "a real password"

Re-running with the same username updates that user's password instead of erroring -
useful for a password reset without needing a "forgot password" flow.
"""

import argparse

import reflex as rx
import sqlmodel
from reflex_local_auth.user import LocalUser

from rxconfig import config

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    with rx.session(url=config.db_url) as session:
        user = session.exec(
            sqlmodel.select(LocalUser).where(LocalUser.username == args.username)
        ).first()
        if user is None:
            user = LocalUser(username=args.username, enabled=True)
            action = "Created"
        else:
            action = "Updated password for"
        user.password_hash = LocalUser.hash_password(args.password)
        user.enabled = True
        session.add(user)
        session.commit()

    print(f"{action} account '{args.username}'.")
