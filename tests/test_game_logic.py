import random
from collections import Counter

from app import game


def test_make_match_exact_positions():
    rng = random.Random(1)
    for _ in range(2000):
        target = game.random_genotype(rng)
        k = rng.choice(list(game.MATCH_WEIGHTS))
        out = game.make_match(target, k, rng)
        assert len(out) == game.LENGTH and set(out) <= set(game.ALPHABET)
        assert game.count_matches(target, out) == k


def test_weight_distribution():
    rng = random.Random(2)
    n = 20000
    c = Counter(game.pick_matches(rng) for _ in range(n))
    for k, w in game.MATCH_WEIGHTS.items():
        assert abs(c[k] / n * 100 - w) < 2, (k, c[k] / n)
    assert set(c) == set(game.MATCH_WEIGHTS)


def test_roll_never_full_match():
    rng = random.Random(3)
    for _ in range(500):
        k, g = game.roll("0123012301", rng)
        assert 5 <= k <= 9 and game.count_matches("0123012301", g) == k


def test_new_genotype_unique():
    rng = random.Random(4)
    taken = set()
    for _ in range(300):
        g = game.new_genotype(lambda x: x in taken, rng)
        assert g not in taken
        taken.add(g)


def test_new_genotype_retries_when_taken():
    rng = random.Random(5)
    first = game.random_genotype(random.Random(5))
    g = game.new_genotype(lambda x: x == first, rng)
    assert g != first
