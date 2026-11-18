
import json
p = '/home/ubuntu/AstrBot/data/config/astrbot_plugin_bilibili_ai_bot_config.json'
d = json.load(open(p, encoding='utf-8-sig'))
d['QQ_GROUP_MUTE'] = True
json.dump(d, open(p, 'w', encoding='utf-8-sig'), ensure_ascii=False, indent=4)
print('QQ_GROUP_MUTE =', d['QQ_GROUP_MUTE'])
