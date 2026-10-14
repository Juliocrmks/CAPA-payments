"""Accuracy benchmark: run extraction on the real packets in references/ and score against the answer key.

    python -m tools.benchmark            (from the project root)
Prints per-payment matches and a field-level accuracy table. Uses a stand-alone registry (no database)."""
import json, os, sys, time
from rapidfuzz import fuzz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from checkflow.extract import process  # noqa: E402
from checkflow.registry import StaticRegistry  # noqa: E402

KEY = os.path.join(ROOT, "tests", "fixtures", "answer_key_2026-10-09.json")
REFS = os.environ.get("CHECKFLOW_REFS", os.path.join(ROOT, "references"))
FIELDS = ("method", "amount", "ticket", "payref", "customer")

def norm(s): return " ".join((s or "").upper().replace(",", " ").replace(".", " ").split())

def match(expected, got):
    """Greedy pairing by amount, then name."""
    pairs, left = [], list(got)
    for e in expected:
        best, bs = None, -1
        for g in left:
            s = (5 if g["fields"].get("amount") == e["amount"] else 0) + (3 if e["payref"] and g["fields"].get("payref") == e["payref"] else 0) \
                + fuzz.token_set_ratio(norm(e["customer"]), norm(g["fields"].get("customer"))) / 100
            if s > bs: best, bs = g, s
        if best is not None and bs >= 0.6: left.remove(best)
        else: best = None
        pairs.append((e, best))
    return pairs, left

def field_ok(f, e, g):
    if g is None: return False
    gv = g["fields"].get(f) or ""
    if f == "customer": return fuzz.token_set_ratio(norm(e[f]), norm(gv)) >= 90
    if f == "payref" and e["method"] in ("wire",): return True
    return (e.get(f) or "") == gv

def run(files=None, verbose=True):
    key = json.load(open(KEY))
    reg = StaticRegistry()
    tot = {f: [0, 0] for f in FIELDS}; found = [0, 0]; extra = 0; secs = 0; npages = 0
    for fn, spec in key.items():
        if fn.startswith("_") or (files and fn not in files): continue
        path = os.path.join(REFS, fn)
        if not os.path.exists(path): print("missing", path); continue
        t = time.time(); res = process(open(path, "rb").read(), fn, reg); secs += time.time() - t; npages += len(res["pages"])
        pairs, left = match(spec["payments"], res["payments"]); extra += len(left)
        if verbose:
            print(f"\n=== {fn}: {len(res['pages'])} pages in {time.time()-t:.0f}s -> {len(res['payments'])} payments (expected {len(spec['payments'])})")
            print("   pages:", " ".join(f"{p['index']+1}:{p['kind']}" for p in res["pages"]))
        for e, g in pairs:
            found[1] += 1; found[0] += g is not None
            row = []
            for f in FIELDS:
                ok = field_ok(f, e, g); tot[f][1] += 1; tot[f][0] += ok
                row.append(("✓" if ok else "✗") + f[:4])
            if verbose:
                gf = g["fields"] if g else {}
                print(f"  {' '.join(row)}  | want {e['customer'][:24]:24} {e['method']:6} {e['amount']:>10} t={e['ticket']:5} r={e['payref']:6}"
                      f" | got {str(gf.get('customer'))[:24]:24} {str(gf.get('method')):6} {str(gf.get('amount')):>10} t={gf.get('ticket','')!s:5} r={gf.get('payref','')!s:6} pages={g['pages'] if g else ''}")
        if verbose:
            for g in left: print("  EXTRA:", {k: g["fields"].get(k) for k in FIELDS}, "pages", g["pages"], g["sources"])
    print(f"\nPayments found {found[0]}/{found[1]}, extra {extra}, {npages} pages in {secs:.0f}s ({secs/max(npages,1):.1f}s/page)")
    for f in FIELDS: print(f"  {f:9} {tot[f][0]:3}/{tot[f][1]}  {100*tot[f][0]/max(tot[f][1],1):5.1f}%")
    return tot, found, extra

if __name__ == "__main__":
    run(sys.argv[1:] or None)
