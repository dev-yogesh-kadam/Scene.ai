"""Where finished images and videos are kept: one folder per user, named after the user's email."""

import re
from pathlib import Path


def folder_name(email):
    """An email as a folder name every system accepts: ada@example.com stays as it is."""
    return re.sub(r"[^\w.@+-]+", "_", email).strip("._ ") or "user"


class Outputs:
    def __init__(self, root, db):
        self.root = Path(root)
        self.db = db
        self.names = {}   # user id -> folder name; an email never changes, so this is filled once per user

    def folder(self, user_id):
        """The folder of one user's finished work. It is not created here."""
        if user_id not in self.names:
            user = self.db.one("SELECT email FROM users WHERE id = ?", (user_id,))
            if user is None:
                return self.root / str(user_id)
            name = folder_name(user["email"])
            # Folders used to be named by user id. One that is still around is renamed the first time it is needed.
            old = self.root / str(user_id)
            if old.is_dir() and not (self.root / name).exists():
                old.rename(self.root / name)
            self.names[user_id] = name
        return self.root / self.names[user_id]
