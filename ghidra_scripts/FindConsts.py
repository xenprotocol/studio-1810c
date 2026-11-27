# List instructions with chosen scalar immediates and their containing function (Jython)
# @category REA
import os
from ghidra.program.model.scalar import Scalar

WANT = set(int(x, 0) for x in os.environ.get(
    "WANT", "0x42,0xa0,0xa1,0xa2,0xa3,0xa4,0x64,0x65,0x194f,0x10c").split(","))
outdir = os.environ.get("DUMP_DIR", "/tmp/ghidra_dump")
prog = currentProgram
fm = prog.getFunctionManager()
hits = []
for ins in prog.getListing().getInstructions(True):
    for i in range(ins.getNumOperands()):
        for o in ins.getOpObjects(i):
            if isinstance(o, Scalar):
                v = o.getUnsignedValue()
                if v in WANT:
                    f = fm.getFunctionContaining(ins.getAddress())
                    hits.append((str(f.getEntryPoint()) if f else "?", f.getName() if f else "?",
                                 hex(v), str(ins.getAddress()), ins.toString()))
fn = os.path.join(outdir, prog.getName() + "_consts.txt")
with open(fn, "w") as fh:
    for h in hits:
        fh.write("%s\t%s\t%s\t%s\t%s\n" % h)
println("wrote %d hits to %s" % (len(hits), fn))
