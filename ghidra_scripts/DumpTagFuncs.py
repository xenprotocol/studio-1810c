# Find functions using the PreSonus packet tag magic values, decompile them (Jython)
# @category REA
import os

TAGS = {0x50617269: "Pari/CMD", 0x64656d73: "dems/STATE"}
prog = currentProgram
fm = prog.getFunctionManager()
outdir = os.environ.get("DUMP_DIR", "/tmp/ghidra_dump")
if not os.path.isdir(outdir):
    os.makedirs(outdir)

hits = {}
for ins in prog.getListing().getInstructions(True):
    for i in range(ins.getNumOperands()):
        for o in ins.getOpObjects(i):
            try:
                v = o.getUnsignedValue()
            except:
                continue
            if v in TAGS:
                f = fm.getFunctionContaining(ins.getAddress())
                if f is not None:
                    hits.setdefault(f.getEntryPoint(), [f, set()])[1].add(TAGS[v])

println("tag functions: %d" % len(hits))
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
ifc = DecompInterface()
ifc.openProgram(prog)
mon = ConsoleTaskMonitor()

out = open(os.path.join(outdir, prog.getName() + "_tags.txt"), "w")
for ep, (f, tags) in sorted(hits.items()):
    out.write("=" * 100 + "\n")
    out.write("FUNC %s @ %s tags=%s\n" % (f.getName(), ep, ",".join(sorted(tags))))
    out.write("=" * 100 + "\n")
    res = ifc.decompileFunction(f, 120, mon)
    if res and res.decompileCompleted():
        out.write(res.getDecompiledFunction().getC())
    out.write("\n\n")
out.close()
println("wrote tags file")
