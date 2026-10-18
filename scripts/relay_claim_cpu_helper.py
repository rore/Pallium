"""Owned private pure-compute helper; no imports from Pallium or SQLite."""
import json, os, sys, time
from pathlib import Path
affinity=sorted(os.sched_getaffinity(0));assert len(affinity)==1
mask=1<<affinity[0]
priority=os.getpriority(os.PRIO_PROCESS,0)
folder=Path(sys.argv[1]); index=int(sys.argv[2])
(folder/f'{index}.ready').write_text(json.dumps({'mask':mask,'priority':priority}))
deadline=int(sys.stdin.readline().strip())
start, cpu=time.monotonic_ns(),time.process_time_ns()
value=1; batches=0
while time.monotonic_ns()<deadline:
 for _ in range(4096): value=(value*1664525+1013904223)&0xffffffff
 batches+=1
end=time.monotonic_ns()
(folder/f'{index}.done').write_text(json.dumps({'start_ns':start,'end_ns':end,'deadline_ns':deadline,'cpu_ns':time.process_time_ns()-cpu,'batches':batches,'mask':mask,'priority':priority}))
