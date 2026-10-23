"""The models the agent uses for each of its roles, as chosen in the admin console; config.json gives the first choice.

- "main": the agent's own model when the user picks none (agent_model)
- "fast": the quicker local model for the small jobs: captions, notes, the check of a skill (ollama_fast_model)
- "vision": the local model that looks at pictures for a model that can't (ollama_vision_model)

An empty choice means config.json's. They are kept in the `agent_roles` setting and set on the Agent as they change,
with no restart. No model is assumed: what Ollama and the hosted services have is what can be chosen.
"""

import json

ROLES = {"main": "model", "fast": "fast", "vision": "vision"}   # role -> the Agent's attribute


def chosen(db):
    try:
        found = json.loads(db.setting("agent_roles", "") or "{}")
    except ValueError:
        found = {}
    return {role: str(found.get(role) or "") for role in ROLES}


def apply(db, agent):
    """Set the chosen models on the agent, over what config.json said (kept as `configured` for an empty choice)."""
    if not hasattr(agent, "configured"):
        agent.configured = {role: getattr(agent, attr) for role, attr in ROLES.items()}
    for role, model in chosen(db).items():
        setattr(agent, ROLES[role], model or agent.configured[role])


def save(db, agent, choices):
    found = {role: str(choices.get(role) or "").strip()[:120] for role in ROLES}
    db.set_setting("agent_roles", json.dumps(found))
    apply(db, agent)
    return found
