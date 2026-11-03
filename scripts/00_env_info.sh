#!/usr/bin/env bash
# Record the machine the experiments run on (results/env.txt).
set -uo pipefail
source "$(dirname "$0")/../config/common.sh"
mkdir -p "$RESULTS" "$DATA_ROOT"
{
  echo "date: $(date -Is)"
  echo "host: $(hostname)"
  echo "kernel: $(uname -srvm)"
  [ -r /etc/os-release ] && . /etc/os-release && echo "os: ${PRETTY_NAME:-unknown}"
  echo "physical cores: $(physical_cores)   logical CPUs: $(nproc)   MAX_THREADS used: $MAX_THREADS"
  echo; echo "## lscpu"; lscpu 2>/dev/null | grep -vi '^flags'
  echo; echo "## memory"; free -h
  echo; echo "## data directory: $DATA_ROOT"; df -hT "$DATA_ROOT"
  dev=$(df --output=source "$DATA_ROOT" | tail -1)
  echo; echo "## block devices"; lsblk -o NAME,MODEL,SIZE,ROTA,TYPE,MOUNTPOINT 2>/dev/null || true
  echo "device of data dir: $dev"
  echo; echo "## CPU frequency governor"
  cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo "n/a"
  echo; echo "## transparent hugepages"
  cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null || echo "n/a"
  echo; echo "## limits"; echo "open files: $(ulimit -n)"
  echo; echo "## compiler"; g++ --version 2>/dev/null | head -1
  echo; echo "## perf"; command -v perf >/dev/null && perf --version || echo "perf not installed"
} > "$RESULTS/env.txt" 2>&1
cat "$RESULTS/env.txt"
