from app.scoring import score_answer

KW = ["value", "cost", "question"]


def test_question_and_keywords_raise_the_score():
    weak, _ = score_answer("It is what it is.", KW)
    strong, tips = score_answer(
        "I see the cost difference, so let me show the value over a full year of claims support. "
        "Which parts of the other offer matter most to your team, and how do you compare them today? "
        "That helps me answer properly.", KW)
    assert strong > weak
    assert tips == []


def test_short_answers_get_a_tip():
    _, tips = score_answer("Fine, I can lower the price?", KW)
    assert any("fuller answer" in t for t in tips)


def test_score_is_bounded():
    s, _ = score_answer("value cost question " * 100 + "?", KW)
    assert 0 <= s <= 100
