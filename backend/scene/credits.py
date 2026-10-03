"""Credits: what a generation costs, and charging and refunding users.

A job is charged when it is queued and refunded if it fails or is cancelled.
"""

import math
import time


class Credits:
    def __init__(self, db, settings):
        self.db = db
        self.settings = settings

    @property
    def per_minute(self):
        return float(self.db.setting("credits_per_minute", self.settings.credits_per_minute))

    @property
    def signup(self):
        return int(float(self.db.setting("signup_credits", self.settings.signup_credits)))

    def cost(self, minutes, clips=1):
        """Credits for one job. `minutes` is the estimated GPU time, or None when there is no estimate yet."""
        if minutes is None:
            return int(self.settings.credits_unknown) * clips
        return max(1, math.ceil(minutes * self.per_minute))

    def balance(self, user_id):
        row = self.db.one("SELECT credits FROM users WHERE id = ?", (user_id,))
        return row["credits"] if row else 0

    def charge(self, user_id, amount, reason, job_id=None):
        """Take credits if the user has enough. Returns False when they don't."""
        if amount <= 0:
            return True
        if not self.db.change("UPDATE users SET credits = credits - ? WHERE id = ? AND credits >= ?",
                              (amount, user_id, amount)):
            return False
        self._log(user_id, -amount, reason, job_id)
        return True

    def add(self, user_id, amount, reason, job_id=None, note=""):
        """Give credits, or take them with a negative amount. A balance never goes below zero.
        Returns the change that was actually made."""
        before = self.balance(user_id)
        amount = max(amount, -before)
        if amount:
            self.db.run("UPDATE users SET credits = credits + ? WHERE id = ?", (amount, user_id))
            self._log(user_id, amount, reason, job_id, note)
        return amount

    def _log(self, user_id, amount, reason, job_id, note=""):
        self.db.run("INSERT INTO credit_events (user_id, amount, reason, job_id, note, created) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, amount, reason, job_id, note, time.time()))
