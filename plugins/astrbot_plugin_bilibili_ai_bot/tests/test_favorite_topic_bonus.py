import unittest

from core.proactive import ProactiveMixin


def make_bot(config=None):
    bot = object.__new__(ProactiveMixin)
    bot.config = config or {}
    return bot


class FavoriteTopicBonusTests(unittest.TestCase):
    def test_strong_keyword_adds_two_points(self):
        bot = make_bot()
        evaluation = {"score": 7, "score_reason": "内容不错"}
        result = bot._apply_favorite_topic_score_bonus(
            evaluation,
            {"title": "大肥鱼二创：今天也在深海里翻滚"},
            "",
        )
        self.assertEqual(result["score"], 9)
        self.assertEqual(result["favorite_topic_bonus"], 2.0)
        self.assertIn("题材相关加成", result["score_reason"])

    def test_weak_keyword_adds_one_point(self):
        bot = make_bot()
        evaluation = {"score": 6.5, "score_reason": "有亮点"}
        result = bot._apply_favorite_topic_score_bonus(
            evaluation,
            {"title": "鲸鱼娘的日常手书"},
            "",
        )
        self.assertEqual(result["score"], 7.5)
        self.assertEqual(result["favorite_topic_bonus"], 1.0)

    def test_bonus_is_capped_at_ten(self):
        bot = make_bot()
        evaluation = {"score": 9.5, "score_reason": "很完整"}
        result = bot._apply_favorite_topic_score_bonus(
            evaluation,
            {"title": "DeepSeek拟人二创"},
            "",
        )
        self.assertEqual(result["score"], 10)

    def test_unrelated_video_is_unchanged(self):
        bot = make_bot()
        evaluation = {"score": 7, "score_reason": "普通视频"}
        result = bot._apply_favorite_topic_score_bonus(
            evaluation,
            {"title": "家常菜教学"},
            "",
        )
        self.assertEqual(result["score"], 7)
        self.assertNotIn("favorite_topic_bonus", result)


if __name__ == "__main__":
    unittest.main()
