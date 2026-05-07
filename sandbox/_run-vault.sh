#!/bin/bash
echo "[Vault search]"
source ~/vault-env/bin/activate
cd ~/vault-search
exec python server.py
