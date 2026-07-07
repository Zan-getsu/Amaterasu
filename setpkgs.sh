#!/bin/bash
# Launch aria2c and SABnzbd daemons with optional CPU throttling.
#
# When running as non-root (the default in the hardened Dockerfile),
# `taskset` requires CAP_SYS_NICE and `cpulimit` requires CAP_SYS_PTRACE.
# If those caps aren't granted (e.g. plain `docker run` without
# --cap-add), we fall back to launching the daemons without throttling
# so the bot can still start. Operators who want throttling should add
# `--cap-add SYS_ADMIN --cap-add SYS_PTRACE --cap-add SYS_NICE` to
# their docker run command, or use docker-compose.yml (which already
# includes them).

ARIA2C=$1
SERVICE_CORES=${2:-}
CPU_LIMIT=${3:-20}
SABNZBDPLUS=$4

# Detect whether taskset and cpulimit actually work for us.
_have_taskset=0
_have_cpulimit=0
if command -v taskset >/dev/null 2>&1 && taskset -c 0 echo >/dev/null 2>&1; then
    _have_taskset=1
fi
if command -v cpulimit >/dev/null 2>&1 && cpulimit -l 100 -z -- true 2>/dev/null; then
    _have_cpulimit=1
fi

if [ "$ARIA2C" != "EXTERNAL_ARIA2" ] && [ -n "$SERVICE_CORES" ] && [ "$_have_taskset" = "1" ]; then
    ARIA2_CMD="taskset -c $SERVICE_CORES $ARIA2C"
else
    ARIA2_CMD="$ARIA2C"
fi

if [ -n "$SABNZBDPLUS" ]; then
    if [ -n "$SERVICE_CORES" ] && [ "$_have_taskset" = "1" ] && [ "$_have_cpulimit" = "1" ]; then
        SAB_CMD="taskset -c $SERVICE_CORES cpulimit -l $CPU_LIMIT -- $SABNZBDPLUS"
    elif [ "$_have_cpulimit" = "1" ]; then
        SAB_CMD="cpulimit -l $CPU_LIMIT -- $SABNZBDPLUS"
    else
        # No cpulimit available (non-root without CAP_SYS_PTRACE).
        # Launch sabnzbd directly — it'll run without CPU throttling.
        SAB_CMD="$SABNZBDPLUS"
    fi
fi

# Fetch tracker list for aria2 (best-effort; fall back to empty list
# if the network is down).
if [ "$ARIA2C" != "EXTERNAL_ARIA2" ]; then
    # Fetch tracker list for aria2 (best-effort; fall back to empty list
    # if the network is down).
    tracker_list=""
    if tracker_list=$(curl -Ns --max-time 10 https://cdn.jsdelivr.net/gh/ngosang/trackerslist@master/trackers_all.txt 2>/dev/null | awk '$0' | tr '\n\n' ','); then
        :
    fi

    if [ -n "$tracker_list" ]; then
        $ARIA2_CMD --conf-path=configs/aria2/aria2.conf --daemon=true --rpc-listen-all=true --bt-tracker="[$tracker_list]"
    else
        echo "[setpkgs.sh] Warning: could not fetch tracker list; starting aria2 without extra trackers"
        $ARIA2_CMD --conf-path=configs/aria2/aria2.conf --daemon=true --rpc-listen-all=true
    fi
fi

if [ -n "$SABNZBDPLUS" ]; then
    $SAB_CMD -f configs/sabnzbd/SABnzbd.ini -s :::8070 -b 0 -d -c -l 0 --console
fi
