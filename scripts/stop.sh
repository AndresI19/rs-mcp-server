#!/usr/bin/env bash
if fuser -k -TERM 8000/tcp > /dev/null 2>&1; then
    echo "Server on port 8000 stopped."
else
    echo "No server running on port 8000."
fi
