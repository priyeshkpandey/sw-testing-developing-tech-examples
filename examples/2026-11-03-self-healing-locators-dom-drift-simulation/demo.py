"""Self-healing locators vs brittle selectors under seeded DOM drift.

Pure stdlib, deterministic. The "AI healer" is a deterministic weighted
similarity scorer (NOT an LLM).
"""
import json
import random
from html.parser import HTMLParser

VOID = {"input", "br", "img", "hr", "meta", "link"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []
        self.text = ""  # direct text
        self.uid = None

    def classes(self):
        return self.attrs.get("class", "").split()

    def path(self):
        out, n = [], self
        while n is not None and n.tag != "#root":
            out.append(n.tag)
            n = n.parent
        return list(reversed(out))

    def full_text(self):
        parts = [self.text] + [c.full_text() for c in self.children]
        return " ".join(p for p in parts if p).strip()


class Builder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = Node("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        d = data.strip()
        if d:
            self.cur.text = (self.cur.text + " " + d).strip()


def parse(html):
    b = Builder()
    b.feed(html)
    assign_uids(b.root)
    return b.root


def assign_uids(root):
    for i, n in enumerate(walk(root)):
        n.uid = i


def walk(n):
    yield n
    for c in n.children:
        yield from walk(c)


def elements(root):
    return [n for n in walk(root) if n.tag != "#root"]


def clone(root):
    def rec(n, parent):
        m = Node(n.tag, n.attrs, parent)
        m.text = n.text
        m.uid = n.uid
        m.children = [rec(c, m) for c in n.children]
        return m
    return rec(root, None)


PAGES = {
    "login": """<html><body><div class="card"><h1>Sign in</h1>
<form id="login-form"><input id="user" class="field" type="text" name="user" placeholder="Username">
<input id="pass" class="field" type="password" name="pass" placeholder="Password">
<button id="submit" class="btn primary" type="submit">Log in</button>
<a id="forgot" class="link" href="/forgot">Forgot password</a></form></div></body></html>""",
    "cart": """<html><body><div class="cart"><h2>Your cart</h2><ul class="items">
<li class="item"><span class="name">Widget</span><button class="btn remove" data-sku="w1">Remove</button></li>
<li class="item"><span class="name">Gadget</span><button class="btn remove" data-sku="g2">Remove</button></li>
<li class="item"><span class="name">Gizmo</span><button class="btn remove" data-sku="z3">Remove</button></li>
</ul><button id="checkout" class="btn primary">Checkout</button></div></body></html>""",
    "table": """<html><body><table class="grid"><tr><th>Name</th><th>Action</th></tr>
<tr class="row"><td>Alice</td><td><button class="btn edit">Edit</button></td></tr>
<tr class="row"><td>Bob</td><td><button class="btn edit">Edit</button></td></tr>
<tr class="row"><td>Carol</td><td><button class="btn edit">Edit</button></td></tr>
</table></body></html>""",
    "nav": """<html><body><nav id="main-nav" class="nav"><a class="nav-link" href="/home">Home</a>
<a class="nav-link" href="/products">Products</a><a class="nav-link" href="/about">About</a>
<a class="nav-link" href="/contact">Contact</a></nav><div class="content"><p class="lead">Welcome</p>
<button id="cta" class="btn primary">Get started</button></div></body></html>""",
    "settings": """<html><body><form class="settings"><label>Email <input class="field" name="email" type="text"></label>
<label>Name <input class="field" name="name" type="text"></label>
<label>City <input class="field" name="city" type="text"></label>
<button class="btn primary" type="submit">Save</button><button class="btn" type="reset">Reset</button></form></body></html>""",
}

# Pages with near-duplicate elements (expected false-heal hot spots).
NEAR_DUP_PAGES = {"cart", "table", "nav", "settings"}


# ---------- locator ----------

def build_selector(target, root):
    """Candidate selectors in preference order; the first that uniquely
    resolves to `target` in `root` is stored. Fallback: nth-path."""
    cands = []
    if target.attrs.get("id"):
        cands.append(("id", target.attrs["id"]))
    for k in ("data-sku", "name"):
        if target.attrs.get(k):
            cands.append((k, target.attrs[k]))
    for c in target.classes():
        cands.append(("class", c))
    if target.classes():
        cands.append(("tagclass", (target.tag, " ".join(target.classes()))))
    for kind, val in cands:
        found = _match(root, (kind, val))
        if len(found) == 1 and found[0] is target:
            return (kind, val)
    # positional fallback: sibling index path
    idx = []
    n = target
    while n.parent is not None:
        idx.append(n.parent.children.index(n))
        n = n.parent
    return ("nth", tuple(reversed(idx)))


def _match(root, sel):
    kind, val = sel
    out = []
    for n in elements(root):
        if kind == "id" and n.attrs.get("id") == val:
            out.append(n)
        elif kind in ("data-sku", "name") and n.attrs.get(kind) == val:
            out.append(n)
        elif kind == "class" and val in n.classes():
            out.append(n)
        elif kind == "tagclass" and n.tag == val[0] and " ".join(n.classes()) == val[1]:
            out.append(n)
    if kind == "nth":
        n = root
        for i in val:
            if i >= len(n.children):
                return []
            n = n.children[i]
        return [n]
    return out


def brittle_locate(root, sel):
    found = _match(root, sel)
    return found[0] if len(found) == 1 else None


def fingerprint(t):
    return {
        "tag": t.tag,
        "text": set(t.full_text().lower().split()),
        "attrs": {k: v for k, v in t.attrs.items()},
        "path": t.path(),
    }


def similarity(fp, n):
    s = 0.0
    if n.tag == fp["tag"]:
        s += 0.25
    a, b = fp["text"], set(n.full_text().lower().split())
    if a or b:
        s += 0.25 * (len(a & b) / len(a | b))
    else:
        s += 0.25
    fa = fp["attrs"]
    keys = set(fa) | set(n.attrs)
    if keys:
        hit = 0.0
        for k in keys:
            if k == "class":
                x, y = set(fa.get(k, "").split()), set(n.classes())
                if x or y:
                    hit += len(x & y) / len(x | y)
            elif fa.get(k) is not None and fa.get(k) == n.attrs.get(k):
                hit += 1
        s += 0.30 * hit / len(keys)
    else:
        s += 0.30
    pa, pb = fp["path"], n.path()
    common = 0
    for x, y in zip(pa, pb):
        if x != y:
            break
        common += 1
    s += 0.20 * common / max(len(pa), len(pb), 1)
    return s


THRESHOLD = 0.55


def heal_locate(root, sel, fp):
    """Try stored selector first; on failure score all elements."""
    n = brittle_locate(root, sel)
    if n is not None:
        return n, "direct", 1.0
    best, best_s = None, -1.0
    for e in elements(root):
        sc = similarity(fp, e)
        if sc > best_s:
            best, best_s = e, sc
    if best is not None and best_s >= THRESHOLD:
        return best, "healed", best_s
    return None, "none", best_s


# ---------- drift mutator ----------

def m_id_rename(root, target, rng):
    changed = False
    for n in elements(root):
        if "id" in n.attrs:
            n.attrs["id"] = n.attrs["id"] + "-v2"
            changed = True
    for n in elements(root):
        if "data-sku" in n.attrs:
            n.attrs["data-sku"] = "x-" + n.attrs["data-sku"]
            changed = True
        if "name" in n.attrs and n is target:
            n.attrs["name"] = n.attrs["name"] + "_f"
            changed = True
    return changed


def m_class_rename(root, target, rng):
    changed = False
    for n in elements(root):
        if "class" in n.attrs:
            n.attrs["class"] = " ".join(c + "-x" for c in n.classes())
            changed = True
    return changed


def m_wrapper(root, target, rng):
    p = target.parent
    w = Node("div", {"class": "wrap"}, p)
    i = p.children.index(target)
    p.children[i] = w
    w.children = [target]
    target.parent = w
    return True


def m_tag_change(root, target, rng):
    newtag = {"button": "a", "a": "button", "input": "textarea", "li": "div",
              "span": "div", "h1": "h2", "h2": "h3", "p": "div", "th": "td"}.get(target.tag)
    if not newtag:
        return False
    target.tag = newtag
    return True


def m_text_reword(root, target, rng):
    if not target.text:
        return False
    words = target.text.split()
    swap = {"Log": "Sign", "in": "on", "Remove": "Delete", "Edit": "Modify", "Checkout": "Pay",
            "Save": "Apply", "Reset": "Clear", "Get": "Begin", "started": "now", "Forgot": "Lost",
            "password": "credentials", "Home": "Start", "Products": "Catalog", "About": "Info",
            "Contact": "Reach", "Sign": "Enter", "Widget": "Thing", "Gadget": "Device"}
    new = [swap.get(w, w + "s") if i == 0 or w in swap else w for i, w in enumerate(words)]
    if new == words:
        new[0] = new[0] + "!"
    target.text = " ".join(new)
    return True


def m_reorder(root, target, rng):
    p = target.parent
    if len(p.children) < 2:
        return False
    i = p.children.index(target)
    p.children.remove(target)
    j = rng.choice([k for k in range(len(p.children) + 1) if k != i])
    p.children.insert(j, target)
    return True


MUTATORS = {
    "id_renamed": m_id_rename,
    "class_renamed": m_class_rename,
    "wrapper_inserted": m_wrapper,
    "tag_changed": m_tag_change,
    "text_reworded": m_text_reword,
    "reordered": m_reorder,
}


# ---------- experiment ----------

def make_cases(seed=1234, n_cases=500):
    rng = random.Random(seed)
    names = list(MUTATORS)
    pages = sorted(PAGES)
    cases = []
    guard = 0
    while len(cases) < n_cases and guard < 100000:
        guard += 1
        page = rng.choice(pages)
        root = parse(PAGES[page])
        els = elements(root)
        target = rng.choice(els)
        if target.tag in ("html", "body"):
            continue
        mut = rng.choice(names)
        sel = build_selector(target, root)
        fp = fingerprint(target)
        mroot = clone(root)
        mt = next(n for n in elements(mroot) if n.uid == target.uid)
        if not MUTATORS[mut](mroot, mt, rng):
            continue
        cases.append({"page": page, "mutation": mut, "target_uid": target.uid,
                      "sel": sel, "fp": fp, "root": mroot})
    return cases


def run(seed=1234, n_cases=500):
    cases = make_cases(seed, n_cases)
    rec = []
    for c in cases:
        b = brittle_locate(c["root"], c["sel"])
        b_ok = b is not None and b.uid == c["target_uid"]
        b_wrong = b is not None and b.uid != c["target_uid"]
        h, how, score = heal_locate(c["root"], c["sel"], c["fp"])
        h_ok = h is not None and h.uid == c["target_uid"]
        h_wrong = h is not None and h.uid != c["target_uid"]
        rec.append({"page": c["page"], "mutation": c["mutation"],
                    "b_ok": b_ok, "b_wrong": b_wrong, "h_ok": h_ok, "h_wrong": h_wrong,
                    "how": how})
    return rec


def rate(xs):
    return round(sum(xs) / len(xs), 4) if xs else 0.0


def build_results(rec):
    n = len(rec)
    b_fail = [not r["b_ok"] for r in rec]
    h_ok = [r["h_ok"] for r in rec]
    # drift cases where brittle didn't find the right element
    broken = [r for r in rec if not r["b_ok"]]
    recovered = [r for r in broken if r["h_ok"]]
    false_heal = [r for r in rec if r["h_wrong"]]
    healed_attempts = [r for r in rec if r["how"] == "healed"]
    not_found = [r for r in rec if r["how"] == "none"]
    summary = {
        "cases": n,
        "brittle_failure_rate": rate(b_fail),
        "brittle_silent_wrong_rate": rate([r["b_wrong"] for r in rec]),
        "healing_success_rate_overall": rate(h_ok),
        "recovery_rate_on_broken": round(len(recovered) / len(broken), 4) if broken else 0.0,
        "false_heal_rate_overall": rate([r["h_wrong"] for r in rec]),
        "false_heal_share_of_heal_attempts": round(
            sum(1 for r in healed_attempts if r["h_wrong"]) / len(healed_attempts), 4)
        if healed_attempts else 0.0,
        "healer_gave_up_rate": rate([r["how"] == "none" for r in rec]),
    }
    muts = list(MUTATORS)
    series_b, series_h, series_fh = [], [], []
    rows = []
    outcomes = []
    for m in muts:
        sub = [r for r in rec if r["mutation"] == m]
        bf = rate([not r["b_ok"] for r in sub])
        hs = rate([r["h_ok"] for r in sub])
        fh = rate([r["h_wrong"] for r in sub])
        series_b.append(round(bf * 100, 1))
        series_h.append(round(hs * 100, 1))
        series_fh.append(round(fh * 100, 1))
        rows.append([m, len(sub), round(bf * 100, 1), round(hs * 100, 1), round(fh * 100, 1)])
        if hs >= 0.85 and fh <= 0.05:
            v = "worked"
        elif hs >= 0.5:
            v = "partial"
        else:
            v = "failed"
        outcomes.append({"case": "drift=" + m, "verdict": v,
                         "evidence": "brittle fail %.1f%%, heal success %.1f%%, false-heal %.1f%% (n=%d)"
                                     % (bf * 100, hs * 100, fh * 100, len(sub))})
    nd = [r for r in rec if r["page"] in NEAR_DUP_PAGES]
    un = [r for r in rec if r["page"] not in NEAR_DUP_PAGES]
    fh_nd, fh_un = rate([r["h_wrong"] for r in nd]), rate([r["h_wrong"] for r in un])
    outcomes.append({"case": "near-duplicate pages (cart/table/nav/settings)",
                     "verdict": "worked" if fh_nd <= 0.05 else ("partial" if fh_nd <= 0.15 else "failed"),
                     "evidence": "false-heal %.1f%% (n=%d) vs %.1f%% on unique-element page (n=%d)"
                                 % (fh_nd * 100, len(nd), fh_un * 100, len(un))})
    summary["false_heal_rate_near_dup_pages"] = fh_nd
    summary["false_heal_rate_unique_pages"] = fh_un
    bw = summary["brittle_silent_wrong_rate"]
    outcomes.append({"case": "brittle selector silently hits wrong element",
                     "verdict": "worked" if bw == 0 else "partial",
                     "evidence": "brittle returned a wrong element in %.1f%% of cases" % (bw * 100)})
    verdict = ("Fingerprint healing recovered %.0f%% of cases that broke brittle selectors (brittle failure %.0f%%), "
               "but healed onto the wrong element in %.1f%% of all cases (%.1f%% on near-duplicate pages), "
               "so healing needs a confidence threshold plus an assertion rather than blind trust."
               % (summary["recovery_rate_on_broken"] * 100, summary["brittle_failure_rate"] * 100,
                  summary["false_heal_rate_overall"] * 100, fh_nd * 100))
    return {
        "verdict": verdict,
        "summary": summary,
        "outcomes": outcomes,
        "chart": {"title": "Failure / healing / false-heal rate by drift type",
                  "ylabel": "percent of cases", "labels": muts,
                  "series": {"brittle failure %": series_b, "heal success %": series_h,
                             "false-heal %": series_fh}},
        "table": {"columns": ["drift", "cases", "brittle fail %", "heal success %", "false-heal %"],
                  "rows": rows},
        "notes": [
            "The 'AI healer' is a deterministic weighted-similarity scorer (tag .25, text .25, attrs .30, path .20); no LLM is used.",
            "Corpus is 5 tiny hand-written pages; real DOMs are larger, noisier, and dynamic (JS, shadow DOM, async).",
            "Mutations are applied one at a time; compound drift (several changes at once) would hurt healing more.",
            "Heal threshold %.2f was fixed before running and not tuned; a different threshold trades success for false-heals." % THRESHOLD,
            "Ground truth is the element's pre-mutation uid, so 'false heal' means healing onto a different element than the one recorded.",
        ],
    }


def main():
    rec = run()
    res = build_results(rec)
    with open("results.json", "w") as f:
        json.dump(res, f, indent=2)
    print(res["verdict"])
    for k, v in res["summary"].items():
        print("  %s: %s" % (k, v))


if __name__ == "__main__":
    main()
