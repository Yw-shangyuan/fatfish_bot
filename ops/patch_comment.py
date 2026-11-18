
path = '/home/ubuntu/AstrBot/data/plugins/astrbot_plugin_bilibili_ai_bot/core/proactive.py'
src = open(path, encoding='utf-8').read()

old = "        comment要求：像真人随手在评论区打的字，只回应一个具体细节；不要概括视频、客套、夸UP辛苦，也不要以“期待下一期”收尾。"
new = """        comment要求：像真人随手在评论区打的字，只回应一个具体细节；不要概括视频、客套、夸UP辛苦，也不要以“期待下一期”收尾。
        comment 不是 review 的缩写，也不是评分理由的口语版——它和 score/review 是两种思维：
        score/review 是给自己看的评价记录；comment 是给别人看的第一反应。
        comment 里不要出现“优点/缺点/亮点/不足/值得改进”这类评审词汇，只写真实的感受、反应或疑问。"""

assert old in src, 'anchor not found'
assert '不是 review 的缩写' not in src, 'already patched'
open(path, 'w', encoding='utf-8').write(src.replace(old, new, 1))
print('proactive.py patched')
