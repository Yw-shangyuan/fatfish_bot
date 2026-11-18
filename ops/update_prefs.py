
import json
p = '/home/ubuntu/AstrBot/data/config/astrbot_plugin_bilibili_ai_bot_config.json'
d = json.load(open(p, encoding='utf-8-sig'))

# 1. 评论风格：真人第一反应，禁止点评腔
d['CUSTOM_PROACTIVE_INSTRUCTION'] = (
    'comment 是你在评论区随手留的一句话，不是影评也不是评分理由的缩写。'
    '看完视频的第一反应是什么就写什么：一个戳中你的细节、一个想吐槽的点、一句真实的疑问都行。'
    '可以只表达感受不评价好坏（如“这段我反复看了三遍”），也可以直接接视频里的梗。'
    '禁止结构化点评（“优点是…缺点是…”）、禁止总结视频内容、禁止客套。'
    '宁可太短太平淡，也不要像测评。'
    '例子：'
    '“3分12秒那个转场我倒回去看了五遍”'
    '“完了，看完想去买电烙铁了”'
    '“这个方案我之前也踩过坑，up这个解法确实聪明”'
)

# 2. 搜索偏好：AI 评测 + AI 娘化二创 + DeepSeek/蓝色大肥鱼
d['PROACTIVE_SEARCH_QUERY_PROMPT'] = (
    '为这一次B站浏览选择1至3个具体搜索词。'
    '偏好方向：AI 相关（大模型评测、AI 新动向、AI 产品实测）和 AI 娘化二创'
    '（尤其是 DeepSeek 娘化、蓝色大肥鱼相关二创）——每 2~3 次搜索里至少一次落在这些方向；'
    '其余搜索词延续有实际观看依据的兴趣，也尝试近期少看的题材。'
    '反复看的主题可以继续保留，但不要只换一个同义词重复搜。'
)

# 3. 偏爱关键词加分：蓝色大肥鱼升强档，补充 AI 评测/娘化弱档
d['PROACTIVE_FAVORITE_STRONG_KEYWORDS'] = ['大肥鱼', '蓝色大肥鱼', 'DeepSeek娘', 'DeepSeek拟人']
d['PROACTIVE_FAVORITE_WEAK_KEYWORDS'] = ['DeepSeek', '鲸鱼娘', 'AI娘二创', '大肥鱼二创', 'AI娘', '娘化', '大模型评测', 'AI评测']
d['PROACTIVE_FAVORITE_STRONG_BONUS'] = 3.0

json.dump(d, open(p, 'w', encoding='utf-8-sig'), ensure_ascii=False, indent=4)
print('config updated')
print('instruction preview:', d['CUSTOM_PROACTIVE_INSTRUCTION'][:60])
