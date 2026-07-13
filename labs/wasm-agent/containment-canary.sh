#!/bin/sh
set -eu

fail=0
check_absent() {
  if [ -e "$1" ]; then
    echo "FAIL unexpected path visible: $1"
    fail=1
  else
    echo "PASS path absent: $1"
  fi
}

check_absent /host-local
check_absent /var/run/docker.sock
check_absent /run/containerd/containerd.sock
check_absent /dev/sda

if touch /lab-canary/agent-write-attempt 2>/dev/null; then
  echo "FAIL external canary was writable"
  fail=1
else
  echo "PASS external canary is read-only"
fi

if touch /local/.safe-lab-write-test; then
  rm /local/.safe-lab-write-test
  echo "PASS lab /local is writable"
else
  echo "FAIL lab /local is not writable"
  fail=1
fi

if [ "$(id -u)" -eq 0 ]; then
  echo "FAIL process runs as root"
  fail=1
else
  echo "PASS process is unprivileged"
fi

if [ "$fail" -ne 0 ]; then
  echo "safe_lab_containment_fail"
  exit 1
fi
echo "safe_lab_containment_pass"
