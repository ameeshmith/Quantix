"""Tests for paragraph-level filing diffing and similarity classification."""


from quantix.services.diff import compute_paragraph_diff


def test_compute_paragraph_diff_exact_matches():
    p1 = [
        "Apple designs and manufactures mobile phones and consumer electronics.",
        "The Company distributes digital content through its online stores.",
    ]
    p2 = [
        "Apple designs and manufactures mobile phones and consumer electronics.",
        "The Company distributes digital content through its online stores.",
    ]
    diff = compute_paragraph_diff(p1, p2)
    assert diff["counts"]["unchanged"] == 2
    assert diff["counts"]["added"] == 0
    assert diff["counts"]["removed"] == 0
    assert diff["counts"]["reworded"] == 0


def test_compute_paragraph_diff_added_and_removed():
    prior = [
        "The Company relies on semiconductor foundries in Asia.",
        "Older legacy paragraph about obsolete technology platform.",
    ]
    current = [
        "The Company relies on semiconductor foundries in Asia.",
        "Newly introduced risk paragraph regarding export controls and tariffs on AI hardware.",
    ]
    diff = compute_paragraph_diff(prior, current)
    assert diff["counts"]["unchanged"] == 1
    assert diff["counts"]["added"] == 1
    assert diff["counts"]["removed"] == 1
    assert diff["counts"]["reworded"] == 0
    assert "export controls" in diff["added"][0]
    assert "obsolete technology" in diff["removed"][0]


def test_compute_paragraph_diff_reworded():
    prior = [
        "Our operations could be affected by global economic slowdowns and rising interest rates.",
    ]
    current = [
        "Our business and operations could be significantly affected by global economic recessions "
        "and fluctuating interest rates in key markets.",
    ]
    diff = compute_paragraph_diff(prior, current)
    assert diff["counts"]["reworded"] == 1
    assert diff["counts"]["added"] == 0
    assert diff["counts"]["removed"] == 0
    reworded = diff["reworded"][0]
    assert reworded["similarity_score"] >= 65.0
    assert "fluctuating interest rates" in reworded["current_text"]
    assert "rising interest rates" in reworded["prior_text"]
