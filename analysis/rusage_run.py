#!/usr/bin/env python3
"""Run a command, save its output, and record its resource usage.

usage: rusage_run.py OUT_JSON OUT_LOG CMD [ARGS...]

stdout of CMD goes to OUT_LOG and stderr to OUT_LOG.err (kept apart so that
db_bench's progress messages cannot interleave with its results). OUT_JSON
gets the wall time and the
child's rusage (user/system CPU seconds, voluntary/involuntary context
switches, block I/O operations, max RSS), so CPU time per lookup can be
computed for the measured phase (WM run minus W run).
"""
import json
import os
import subprocess
import sys
import time


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        return 2
    out_json, out_log, cmd = sys.argv[1], sys.argv[2], sys.argv[3:]
    start = time.time()
    with open(out_log, "wb") as log, open(out_log + ".err", "wb") as err:
        proc = subprocess.Popen(cmd, stdout=log, stderr=err)
        _, status, ru = os.wait4(proc.pid, 0)
    wall = time.time() - start
    rc = os.waitstatus_to_exitcode(status)
    record = {
        "returncode": rc,
        "wall_s": wall,
        "utime_s": ru.ru_utime,
        "stime_s": ru.ru_stime,
        "maxrss_kb": ru.ru_maxrss,
        "nvcsw": ru.ru_nvcsw,
        "nivcsw": ru.ru_nivcsw,
        "inblock": ru.ru_inblock,
        "oublock": ru.ru_oublock,
        "minflt": ru.ru_minflt,
        "majflt": ru.ru_majflt,
        "start_epoch": start,
    }
    with open(out_json, "w") as f:
        json.dump(record, f, indent=1)
    return rc


if __name__ == "__main__":
    sys.exit(main())
