from trend_system.deduplication.hash_dedup import content_hash, is_exact_duplicate, simhash_approx, is_near_duplicate

def test_hash_dedup():
    h1 = content_hash("hello world")
    h2 = content_hash("hello world")
    h3 = content_hash("hello world!")
    assert is_exact_duplicate(h1,h2)
    assert not is_exact_duplicate(h1,h3)

def test_near_dup():
    fp1 = simhash_approx("wide leg trousers are trending in Tehran")
    fp2 = simhash_approx("wide leg trousers are trending in Tehran")
    fp3 = simhash_approx("completely different content about cooking recipes")
    assert is_near_duplicate(fp1,fp2)
    assert not is_near_duplicate(fp1,fp3)
