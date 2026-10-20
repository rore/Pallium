"""Only restore the captured original process context, then exec the fixed child."""
import json
import os
from pathlib import Path
import sys

request = Path(sys.argv[1])
payload = json.loads(request.read_text())
assert os.geteuid() == 0 and payload["uid"] > 0
os.setgroups(payload["groups"])
os.setgid(payload["gid"])
os.setuid(payload["uid"])
os.chdir(payload["cwd"])
os.umask(payload["umask"])
assert os.getuid() == os.geteuid() == payload["uid"]
assert os.getgid() == os.getegid() == payload["gid"]
assert sorted(os.getgroups()) == sorted(payload["groups"])
environment = payload["environment"]
mode = sys.argv[2]
assert mode in {"preflight", "runner"}
current_mask = os.umask(payload["umask"])
assert current_mask == payload["umask"]
target = payload["preflight"] if mode == "preflight" else payload["runner"]
if mode == "runner":
    from hashlib import sha256
    outcome = dict(uid=os.getuid(), gid=os.getgid(), groups=sorted(os.getgroups()),
                   cwd=os.getcwd(), umask=payload["umask"],
                   environment_sha256=sha256(json.dumps(environment, sort_keys=True).encode()).hexdigest())
    Path(payload["output"], "native", "launcher-context.json").write_text(json.dumps(outcome, indent=2))
os.execve(payload["python"], [payload["python"], target], environment)

