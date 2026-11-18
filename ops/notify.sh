#!/usr/bin/env bash
# usage: notify.sh "message text"
T=$(python3 -c "import json,sys;print(json.dumps({'user_id':3406408181,'message':[{'type':'text','data':{'text':sys.argv[1]}}]},ensure_ascii=True))" "$1")
curl -s -m 6 -X POST http://127.0.0.1:3000/send_private_msg -H "Content-Type: application/json" -d "$T"
echo ""