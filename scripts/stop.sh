#!/usr/bin/env bash
if ! fuser -s 8000/tcp 2>/dev/null; then
    echo "No server running on port 8000."
    exit 0
fi

fuser -s -k -TERM 8000/tcp 2>/dev/null

for _ in $(seq 1 50); do
    sleep 0.1
    if ! fuser -s 8000/tcp 2>/dev/null; then
        echo "Server on port 8000 stopped."
        exit 0
    fi
done

fuser -s -k -KILL 8000/tcp 2>/dev/null
sleep 0.2
echo "Server on port 8000 force-killed (didn't respond to SIGTERM within 5s)."
