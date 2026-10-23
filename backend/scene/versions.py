"""Every version of every workflow, as the render PC hands them over: what arrived when, and what changed.

A version is a workflow file and its presets file (<name>.studio.json) as they were. Each one is kept, once, in
storage/workflow_versions/<hash>.json.gz, and the `workflow_versions` table records when it was first seen: "first" for
what was there when the record began, then "new", "updated" and "removed". Looking again costs almost nothing while
no file has changed (the watcher looks every minute, the console when its Workflows section opens).

Also here: what a workflow needs that the render server did not have when its node list was last saved (model files
and node types), and what changed between two versions, node by node.
"""

import gzip
import hashlib
import json
import re
import time
from pathlib import Path

# An input whose value names a model file.
MODEL_FILE = re.compile(r"\.(safetensors|ckpt|pt|pth|bin|gguf|sft|onnx)$", re.I)
# Nodes that only exist in ComfyUI's page, never on the server: not "missing" when the node list lacks them.
PAGE_ONLY = {"Note", "MarkdownNote", "Reroute", "PrimitiveNode", "PrimitiveString", "PrimitiveInt", "PrimitiveFloat",
             "PrimitiveBoolean", "Fast Groups Bypasser (rgthree)", "Fast Groups Muter (rgthree)", "Label (rgthree)"}


AUDIENCES = ("everyone", "admins", "off")
NODES_STALE = 6 * 3600   # a node list older than this is fetched again once the render server answers


def set_audience(db, workflow_id, audience):
    """Who is offered a workflow: everyone, admins alone (to try it first), or nobody (switched off). Its pricing stays."""
    db.run("INSERT INTO workflow_pricing (workflow, enabled, admins_only) VALUES (?, ?, ?) "
           "ON CONFLICT (workflow) DO UPDATE SET enabled = excluded.enabled, admins_only = excluded.admins_only",
           (workflow_id, int(audience != "off"), int(audience == "admins")))


def audience(row):
    """The audience of a workflow from its pricing row (None: it has none, so everyone)."""
    if row and not row["enabled"]:
        return "off"
    return "admins" if row and row["admins_only"] else "everyone"


def look(state):
    """Record any change to the workflow files. A new workflow is offered to admins alone first when the console says
    so (setting new_workflows_admins_only)."""
    hold = state.db.setting("new_workflows_admins_only", "0") == "1"
    return state.versions.scan(new_admins_only=(lambda workflow_id: set_audience(state.db, workflow_id, "admins")) if hold else None)


class Shelf:
    """The kept versions of one installation's workflows."""

    def __init__(self, db, catalog, folder):
        self.db, self.catalog, self.folder = db, catalog, Path(folder)
        self.signature = None   # the files' names, sizes and times at the last look

    def _files(self):
        """Workflow id -> (its file, its presets file or None)."""
        found = {}
        for workflow_id, path in self.catalog.files().items():
            sidecar = self.catalog.sidecar_of(path)
            found[workflow_id] = (path, sidecar if sidecar.is_file() else None)
        return found

    def scan(self, now=None, new_admins_only=None):
        """Record what changed since the last look. Returns [(workflow id, change)]. `new_admins_only(workflow id)` is
        called for each new workflow (not for the first record)."""
        files = self._files()
        signature = sorted((wid, *(str(p) + ":" + str(p.stat().st_size) + ":" + str(p.stat().st_mtime_ns) for p in pair if p))
                           for wid, pair in files.items())
        if signature == self.signature:
            return []
        now = now or time.time()
        latest = self.latest()
        first = not latest
        changes = []
        for workflow_id, (path, sidecar) in files.items():
            try:
                graph = path.read_text(encoding="utf-8")
                presets = sidecar.read_text(encoding="utf-8") if sidecar else ""
            except OSError:
                continue
            digest = hashlib.sha256((graph + "\0" + presets).encode("utf-8")).hexdigest()[:20]
            last = latest.get(workflow_id)
            if last and last["change"] != "removed" and last["hash"] == digest:
                continue
            kept = self.folder / (digest + ".json.gz")
            if not kept.is_file():
                self.folder.mkdir(parents=True, exist_ok=True)
                kept.write_bytes(gzip.compress(json.dumps({"file": path.name, "graph": graph, "presets": presets}).encode("utf-8")))
            change = "first" if first else "new" if not last or last["change"] == "removed" else "updated"
            self.db.run("INSERT INTO workflow_versions (workflow, hash, change, seen) VALUES (?, ?, ?, ?)", (workflow_id, digest, change, now))
            changes.append((workflow_id, change))
            if change == "new" and new_admins_only:
                new_admins_only(workflow_id)
        for workflow_id, last in latest.items():
            if workflow_id not in files and last["change"] != "removed":
                self.db.run("INSERT INTO workflow_versions (workflow, hash, change, seen) VALUES (?, '', 'removed', ?)", (workflow_id, now))
                changes.append((workflow_id, "removed"))
        self.signature = signature
        return changes

    def latest(self):
        """Workflow id -> its newest record."""
        return {r["workflow"]: r for r in self.db.all(
            "SELECT * FROM workflow_versions WHERE id IN (SELECT MAX(id) FROM workflow_versions GROUP BY workflow)")}

    def drops(self, limit=12):
        """The looks that found something, newest first: when, and what was new, updated or removed."""
        rows = self.db.all("SELECT workflow, change, seen FROM workflow_versions WHERE change != 'first' ORDER BY seen DESC, workflow")
        found = []
        for row in rows:
            if not found or found[-1]["seen"] != row["seen"]:
                if len(found) == limit:
                    break
                found.append({"seen": row["seen"], "new": [], "updated": [], "removed": []})
            found[-1][row["change"]].append(row["workflow"])
        first = self.db.one("SELECT MIN(seen) AS seen FROM workflow_versions WHERE change = 'first'")
        return {"drops": found, "since": first["seen"] if first else None}

    def kept(self, digest):
        try:
            return json.loads(gzip.decompress((self.folder / (digest + ".json.gz")).read_bytes()))
        except (OSError, ValueError, EOFError):
            return None

    def history(self, workflow_id):
        """Every version of one workflow, newest first, each with what changed from the one before."""
        rows = self.db.all("SELECT * FROM workflow_versions WHERE workflow = ? ORDER BY id", (workflow_id,))
        found, before = [], None
        for row in rows:
            now = self.kept(row["hash"]) if row["hash"] else None
            lines = diff(before, now) if before and now else []
            found.append({"id": row["id"], "change": row["change"], "seen": row["seen"], "file": (now or {}).get("file", ""), "changes": lines})
            before = now or before
        return list(reversed(found))


# ---------------------------------------------------------------- what changed

def _graph(text):
    """A workflow's nodes, in either of ComfyUI's formats: node id -> (type, title, its settings)."""
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    if isinstance(data, dict) and isinstance(data.get("nodes"), list):   # as saved from ComfyUI's page
        nodes = list(data["nodes"])
        for graph in (data.get("definitions") or {}).get("subgraphs") or []:
            nodes += [dict(n, id="{}:{}".format(graph.get("name") or graph.get("id"), n.get("id"))) for n in graph.get("nodes") or []]
        return {str(n.get("id")): (n.get("type", ""), n.get("title") or "", {"values": n.get("widgets_values")},
                                   n.get("mode", 0)) for n in nodes if isinstance(n, dict)}
    if isinstance(data, dict):   # API format
        return {str(k): (v.get("class_type", ""), (v.get("_meta") or {}).get("title", ""),
                         {name: value for name, value in (v.get("inputs") or {}).items() if not isinstance(value, list)}, 0)
                for k, v in data.items() if isinstance(v, dict)}
    return {}


def _short(value, limit=60):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else '"{}"'.format(value)
    return text if len(text) <= limit else text[:limit - 1] + "…"


MODES = {0: "on", 2: "muted", 4: "bypassed"}


def diff(old, new):
    """What changed from one kept version to the next, in lines a person reads: nodes added, removed, switched and
    settings changed, then the presets file's entries."""
    lines = []
    if old["file"] != new["file"]:
        lines.append("File: {} → {}".format(old["file"], new["file"]))
    a, b = _graph(old["graph"]), _graph(new["graph"])

    def name(nid, node):
        return "Node {} ({})".format(nid, node[1] if node[1] and node[1] != node[0] else node[0])
    for nid in sorted(set(b) - set(a), key=_order):
        lines.append("Added " + name(nid, b[nid]))
    for nid in sorted(set(a) - set(b), key=_order):
        lines.append("Removed " + name(nid, a[nid]))
    for nid in sorted(set(a) & set(b), key=_order):
        was, now = a[nid], b[nid]
        if was[0] != now[0]:
            lines.append("{}: became {}".format(name(nid, was), now[0]))
            continue
        if was[3] != now[3]:
            lines.append("{}: {} → {}".format(name(nid, now), MODES.get(was[3], was[3]), MODES.get(now[3], now[3])))
        for key in sorted(set(was[2]) | set(now[2])):
            if was[2].get(key) != now[2].get(key):
                label = "" if key == "values" else key + ": "
                lines.append("{}: {}{} → {}".format(name(nid, now), label, _short(was[2].get(key)), _short(now[2].get(key))))
    try:
        p, q = json.loads(old["presets"] or "{}"), json.loads(new["presets"] or "{}")
    except ValueError:
        p, q = {}, {}
    for key in sorted(set(p) | set(q)):
        if p.get(key) != q.get(key):
            if key not in p:
                lines.append("Presets: added {}".format(key))
            elif key not in q:
                lines.append("Presets: removed {}".format(key))
            elif all(isinstance(v, (str, int, float, bool)) for v in (p[key], q[key])):
                lines.append("Presets: {} {} → {}".format(key, _short(p[key]), _short(q[key])))
            else:
                lines.append("Presets: {} changed".format(key))
    return lines


def _order(nid):
    parts = re.findall(r"\d+|\D+", nid)
    return [(0, int(x)) if x.isdigit() else (1, x) for x in parts]


# ---------------------------------------------------------------- what the render server lacks

def _choices(spec):
    """The values an input may take, from ComfyUI's node list: [["a", "b"], {...}] or ["COMBO", {"options": [...]}]."""
    if not isinstance(spec, list) or not spec:
        return None
    if isinstance(spec[0], list):
        return spec[0]
    if spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        return spec[1].get("options")
    return None


def _same(path):
    return path.replace("\\", "/").lower()


def missing(wf, object_info):
    """The node types and model files a loaded workflow uses that the render server did not have, as its node list
    says: {"nodes": [type], "files": [{node, type, input, file}]}. None when there is no node list to compare with.
    Muted and bypassed nodes don't count: they don't run."""
    if not object_info:
        return None
    nodes, files = set(), []
    for nid, node in wf["nodes"].items():
        meta = wf["info"].get(nid, {})
        if meta.get("virtual") or meta.get("mode") in (2, 4):
            continue
        kind = node.get("class_type", "")
        spec = object_info.get(kind)
        if spec is None:
            if kind and kind not in PAGE_ONLY:
                nodes.add(kind)
            continue
        inputs = {**(spec.get("input") or {}).get("required", {}), **(spec.get("input") or {}).get("optional", {})}
        for name, value in (node.get("inputs") or {}).items():
            if isinstance(value, str) and MODEL_FILE.search(value):
                choices = _choices(inputs.get(name))
                if isinstance(choices, list) and _same(value) not in {_same(str(c)) for c in choices}:
                    files.append({"node": nid, "type": kind, "input": name, "file": value})
    return {"nodes": sorted(nodes), "files": files}
