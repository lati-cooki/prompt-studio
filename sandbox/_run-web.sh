#!/bin/bash
echo "[Web server]"
cd ~/prompt-sandbox
exec python3 -m http.server 7777
