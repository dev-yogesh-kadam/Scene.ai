"""Credits: what a generation costs, and charging and refunding users.

The price is what the customer asked for, never the GPU time it took: an image costs a flat amount, and a video,
a sound, a motion graphic, a title laid over a video or an upscale costs an amount per second of the result. An admin sets the rates in the
admin console (Pricing), for each kind and, where one needs its own, for a single workflow.

A job is charged when it is queued and refunded if it fails or is cancelled.
"""

import math
import time

# The rates a new installation starts with. Per generation for the kinds in PER_JOB, per second for the rest.
RATES = {"image": 40, "video": 20, "audio": 5, "motion": 30, "overlay": 10, "upscaler": 20}
PER_JOB = ("image",)
MOTION = "edit/motion"       # what a motion graphic is priced and filed under; it has no workflow file
OVERLAY = "edit/overlay"     # what a motion graphic laid over a video the user has is priced under
ASSUMED_SECONDS = 5          # billed when a per-second workflow does not say how long its result is
INR_PER_1000_CREDITS = 100
ELECTRICITY_INR_PER_KWH = 8


def kind_of(workflow_id):
    return {MOTION: "motion", OVERLAY: "overlay"}.get(workflow_id) or workflow_id.split("/", 1)[0]


class Credits:
    def __init__(self, db, settings):
        self.db = db
        self.settings = settings

    @property
    def signup(self):
        return int(float(self.db.setting("signup_credits", self.settings.signup_credits)))

    @property
    def inr_per_1000(self):
        return float(self.db.setting("inr_per_1000_credits", INR_PER_1000_CREDITS))

    @property
    def electricity_rate(self):
        return float(self.db.setting("electricity_inr_per_kwh", ELECTRICITY_INR_PER_KWH))

    def rates(self):
        return {kind: float(self.db.setting("rate_" + kind, default)) for kind, default in RATES.items()}

    def pricing(self, workflow_id):
        """The workflow's own pricing, or None when it follows the rate of its kind."""
        return self.db.one("SELECT * FROM workflow_pricing WHERE workflow = ?", (workflow_id,))

    def enabled(self, workflow_id):
        row = self.pricing(workflow_id)
        return not row or bool(row["enabled"])

    def rate_for(self, workflow_id):
        """(base credits, credits per second, multiplier) for one workflow."""
        kind = kind_of(workflow_id)
        rate = self.rates().get(kind, 0)
        base, per_second = (rate, 0) if kind in PER_JOB else (0, rate)
        row = self.pricing(workflow_id) or {}
        if row.get("base_credits") is not None:
            base = row["base_credits"]
        if row.get("credits_per_second") is not None:
            per_second = row["credits_per_second"]
        return base, per_second, row.get("resolution_multiplier", 1) * row.get("quality_multiplier", 1)

    def cost(self, workflow_id, seconds=None):
        """Credits for one job. `seconds` is the length of the result that was asked for, when it has one."""
        base, per_second, multiplier = self.rate_for(workflow_id)
        seconds = ASSUMED_SECONDS if seconds is None else seconds
        return math.ceil(round((base + per_second * seconds) * multiplier, 6))

    def balance(self, user_id):
        row = self.db.one("SELECT credits FROM users WHERE id = ?", (user_id,))
        return row["credits"] if row else 0

    def charge(self, user_id, amount, reason, job_id=None, note=""):
        """Take credits if the user has enough. Returns False when they don't."""
        if amount <= 0:
            return True
        if not self.db.change("UPDATE users SET credits = credits - ? WHERE id = ? AND credits >= ?",
                              (amount, user_id, amount)):
            return False
        self._log(user_id, -amount, reason, job_id, note)
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
