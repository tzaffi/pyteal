import pstats
import sys

pfile = f"profile_{sys.version_info.minor}"
print(f"reading {pfile}")
p = pstats.Stats(pfile)
# p.strip_dirs()
p.sort_stats('cumtime')
p.print_stats(1000)