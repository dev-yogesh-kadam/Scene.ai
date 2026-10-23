"""Credits: what a generation costs, and charging and refunding users.

The price is what the customer asked for, never the GPU time it took: an image costs a flat amount, and a video,
a sound, a motion graphic, a title laid over a video or an upscale costs an amount per second of the result. An admin sets the rates in the
admin console (Pricing), for each kind and, where one needs its own, for a single workflow.

What was chosen changes the price too: a resolution and a quality each multiply it (FACTORS), so a 480p draft costs
less than a 1080p final. The factors are the studio's, set in the console, and a workflow may have its own.

A job is charged when it is queued and refunded if it fails or is cancelled.
"""

import math
import json
import time

# The rates a new installation starts with. Per generation for the kinds in PER_JOB, per second for the rest.
RATES = {"image": 40, "video": 20, "audio": 5, "motion": 30, "overlay": 10, "upscaler": 20}
PER_JOB = ("image",)
MOTION = "edit/motion"       # what a motion graphic is priced and filed under; it has no workflow file
OVERLAY = "edit/overlay"     # what a motion graphic laid over a video the user has is priced under
ASSUMED_SECONDS = 5          # billed when a per-second workflow does not say how long its result is
# How much each resolution and quality multiplies the price, to begin with. 720p and final cost the rate itself; 768p (the
# short edge MiniMax H3 renders at) is priced as 720p. Quality is "draft"/"final" for most workflows and
# "low"/"medium"/"high" for some video ones. A picture is priced by its quality only, not its size.
FACTORS = {"resolution": {"480": 0.6, "720": 1.0, "1080": 2.0},
           "quality": {"draft": 0.5, "final": 1.0, "low": 0.6, "medium": 0.8, "high": 1.0}}
RESOLUTION_TIER = {480: "480", 720: "720", 768: "720", 1080: "1080"}
INR_PER_1000_CREDITS = 100
ELECTRICITY_INR_PER_KWH = 8


def _number(value):
    try:
        return float(value) >= 0
    except (TypeError, ValueError):
        return False


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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

    def llm_prices(self):
        """What a message to the agent costs, by model: {"gemini/gemini-3.6-flash": 2}. A model not listed is free."""
        try:
            found = json.loads(self.db.setting("llm_prices", "{}") or "{}")
        except ValueError:
            found = {}
        return {str(k): int(v) for k, v in found.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0}

    def set_llm_price(self, model, credits):
        prices = self.llm_prices()
        if credits:
            prices[model] = int(credits)
        else:
            prices.pop(model, None)
        self.db.set_setting("llm_prices", json.dumps(prices))

    def llm_cost(self, model):
        return self.llm_prices().get(str(model or ""), 0)

    def pricing(self, workflow_id):
        """The workflow's own pricing, or None when it follows the rate of its kind."""
        return self.db.one("SELECT * FROM workflow_pricing WHERE workflow = ?", (workflow_id,))

    def enabled(self, workflow_id, user=None):
        """Whether `user` may use the workflow: it is switched on and, while it is tried out by admins alone (the
        console's Workflows section), they are one. With no user, as for anyone who is not an admin."""
        row = self.pricing(workflow_id)
        if not row:
            return True
        return bool(row["enabled"]) and (not row["admins_only"] or bool(user and user.get("role") == "admin"))

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

    def cost(self, workflow_id, seconds=None, chosen=None):
        """Credits for one job. `seconds` is the length of the result that was asked for, when it has one; `chosen`, what
        was picked (the job's context: its resolution and quality), which multiplies the price (factors)."""
        base, per_second, multiplier = self.rate_for(workflow_id)
        seconds = ASSUMED_SECONDS if seconds is None else seconds
        return math.ceil(round((base + per_second * seconds) * multiplier * self.choice_factor(workflow_id, chosen), 6))

    def factors(self, workflow_id=None):
        """The resolution and quality factors in force: the studio's (setting price_factors, over FACTORS), and over them
        a workflow's own, when it has some (workflow_pricing.factors)."""
        found = {group: dict(values) for group, values in FACTORS.items()}
        for layer in (self._json(self.db.setting("price_factors", "") or "{}"),
                      self._json((self.pricing(workflow_id) or {}).get("factors") or "{}") if workflow_id else {}):
            for group in found:
                found[group].update({str(k): float(v) for k, v in (layer.get(group) or {}).items() if _number(v)})
        return found

    def choice_factor(self, workflow_id, chosen):
        """What the chosen resolution and quality multiply a workflow's price by (1 for what has no factor)."""
        if not chosen:
            return 1.0
        found, factor = self.factors(workflow_id), 1.0
        tier = RESOLUTION_TIER.get(_int(chosen.get("resolution")))
        if tier and kind_of(workflow_id) not in PER_JOB:   # a picture is priced by its quality, not its size
            factor *= found["resolution"].get(tier, 1.0)
        if chosen.get("quality") is not None:
            factor *= found["quality"].get(str(chosen["quality"]), 1.0)
        return factor

    @staticmethod
    def _json(text):
        try:
            found = json.loads(text)
        except (TypeError, ValueError):
            return {}
        return found if isinstance(found, dict) else {}

    @property
    def daily_cap(self):
        """The most credits one user may spend in 24 hours, unless an admin set their own. 0 means no limit."""
        return int(float(self.db.setting("daily_cap", 0)))

    def cap_for(self, user):
        own = user.get("daily_cap")
        return self.daily_cap if own is None else own

    def spent_today(self, user_id):
        """Credits spent in the last 24 hours: charges, less what was refunded."""
        row = self.db.one("SELECT SUM(amount) n FROM credit_events WHERE user_id = ? AND reason IN ('generation', 'refund', 'agent') "
                          "AND created > ?", (user_id, time.time() - 86400))
        return max(0, -(row["n"] or 0))

    def cap_problem(self, user_id, amount):
        """Why a charge of `amount` would go over the user's daily limit, or None. Admins have no limit."""
        user = self.db.one("SELECT role, daily_cap FROM users WHERE id = ?", (user_id,))
        if not user or user["role"] == "admin" or amount <= 0:
            return None
        cap = self.cap_for(user)
        spent = self.spent_today(user_id)
        if cap and spent + amount > cap:
            return ("This needs {} credits. Your account can spend {} in 24 hours and has spent {} already. "
                    "Try again later, or ask an admin.".format(amount, cap, spent))
        return None

    def balance(self, user_id):
        row = self.db.one("SELECT credits FROM users WHERE id = ?", (user_id,))
        return row["credits"] if row else 0

    def charge(self, user_id, amount, reason, job_id=None, note="", project_id=None):
        """Take credits if the user has enough. Returns False when they don't. `project_id`: the project it was spent in,
        when no job says so (a message to the agent)."""
        if amount <= 0:
            return True
        if not self.db.change("UPDATE users SET credits = credits - ? WHERE id = ? AND credits >= ?",
                              (amount, user_id, amount)):
            return False
        self._log(user_id, -amount, reason, job_id, note, project_id)
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

    def _log(self, user_id, amount, reason, job_id, note="", project_id=None):
        self.db.run("INSERT INTO credit_events (user_id, amount, reason, job_id, note, created, project_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, amount, reason, job_id, note, time.time(), project_id))
