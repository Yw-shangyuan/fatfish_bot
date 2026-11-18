
import json, re
print(open('/home/ubuntu/AstrBot/astrbot/core/pipeline/process_stage/follow_up.py', encoding='utf-8').read()[:2500])
print('===CONFIG===')
d = json.load(open('/home/ubuntu/AstrBot/data/cmd_config.json', encoding='utf-8-sig'))
s = json.dumps(d, ensure_ascii=False)
for m in re.finditer(r'"[a-zA-Z_]*(?:follow|continue|session)[a-zA-Z_]*"\s*:\s*[^,}]+', s):
    print(m.group(0))
