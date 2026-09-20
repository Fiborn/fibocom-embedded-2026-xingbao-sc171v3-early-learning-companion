from intelligence.profile_extractor import ProfileExtractor


def test_profile_extractor_collects_allowed_interests_and_games() -> None:
    result = ProfileExtractor().extract("我喜欢画画，也喜欢玩积木，我今天很开心")

    assert result.updates["interests"] == ["画画"]
    assert result.updates["favorite_games"] == ["积木"]
    assert result.updates["recent_mood"] == "happy"
    assert result.ignored_sensitive is False


def test_profile_extractor_treats_story_topics_as_interests() -> None:
    result = ProfileExtractor().extract("我想听一个恐龙的故事")

    assert result.updates["interests"] == ["恐龙"]
    assert result.updates["recent_topics"] == ["恐龙"]


def test_profile_extractor_ignores_sensitive_clauses() -> None:
    result = ProfileExtractor().extract("我喜欢画画，我的家庭地址在某小区，我喜欢玩拼图")

    assert result.updates["interests"] == ["画画"]
    assert result.updates["favorite_games"] == ["拼图"]
    assert result.ignored_sensitive is True
    assert "地址" not in str(result.updates)


def test_profile_extractor_collects_communication_style() -> None:
    result = ProfileExtractor().extract("以后请简单说，也给我选项，再夸夸我")

    assert result.updates["communication_style"] == {
        "likes_short_answers": True,
        "needs_encouragement": True,
        "prefers_choice_questions": True,
    }
