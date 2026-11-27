# Dump per-function referenced strings + callees to CSV (Jython, Ghidra 11)
# @category REA
import os, csv

prog = currentProgram
fm = prog.getFunctionManager()
listing = prog.getListing()
outdir = os.environ.get("DUMP_DIR", "/tmp/ghidra_dump")
if not os.path.isdir(outdir):
    os.makedirs(outdir)

def str_at(addr):
    d = listing.getDataAt(addr)
    if d is None:
        return None
    try:
        if d.hasStringValue():
            return d.getValue()
    except:
        pass
    return None

rows = []
total = fm.getFunctionCount()
i = 0
for f in fm.getFunctions(True):
    i += 1
    if i % 500 == 0:
        println("progress %d/%d" % (i, total))
    refs = []
    body = f.getBody()
    # strings referenced from body
    for a in body.getAddresses(True):
        for r in prog.getReferenceManager().getReferencesFrom(a):
            s = str_at(r.getToAddress())
            if s is not None:
                refs.append(s)
    callees = []
    for a in body.getAddresses(True):
        for r in prog.getReferenceManager().getReferencesFrom(a):
            tf = fm.getFunctionContaining(r.getToAddress())
            if tf is not None and tf.getEntryPoint() != f.getEntryPoint():
                callees.append(tf.getName())
    if refs or callees:
        rows.append([f.getName(), str(f.getEntryPoint()), ",".join(sorted(set(refs)))[:4000], ",".join(sorted(set(callees)))[:2000]])

fn = os.path.join(outdir, prog.getName() + "_funcs.csv")
with open(fn, "w") as fh:
    w = csv.writer(fh)
    w.writerow(["func", "ea", "strings", "callees"])
    w.writerows(rows)
println("wrote %s (%d functions with refs)" % (fn, len(rows)))
