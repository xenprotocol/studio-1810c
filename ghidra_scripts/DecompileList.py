# Decompile an explicit list of addresses (Jython)
# @category REA
import os
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

addrs = [a.strip() for a in os.environ.get("ADDRS", "").split(",") if a.strip()]
outdir = os.environ.get("DUMP_DIR", "/tmp/ghidra_dump")
tag = os.environ.get("TAG", "targets")
prog = currentProgram
ifc = DecompInterface()
ifc.openProgram(prog)
mon = ConsoleTaskMonitor()
fm = prog.getFunctionManager()
out = open(os.path.join(outdir, prog.getName() + "_" + tag + ".txt"), "w")
for a in addrs:
    addr = prog.getAddressFactory().getAddress(a)
    f = fm.getFunctionContaining(addr)
    if f is None:
        out.write("no function at %s\n" % a)
        continue
    out.write("=" * 100 + "\n%s @ %s\n" % (f.getName(), f.getEntryPoint()) + "=" * 100 + "\n")
    res = ifc.decompileFunction(f, 180, mon)
    if res and res.decompileCompleted():
        out.write(res.getDecompiledFunction().getC())
    else:
        out.write("decompile failed\n")
    out.write("\n\n")
out.close()
println("done")
