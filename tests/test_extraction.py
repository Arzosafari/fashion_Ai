from trend_system.extraction.text_extractor import extract_clean_text, content_hash, detect_language

def test_extract_clean_text():
    html = "<html><head><title>Test Title</title><meta property='article:published_time' content='2026-09-18T12:00:00Z'/></head><body><article>Wide leg trousers are trending</article></body></html>"
    res = extract_clean_text(html, "https://www.vogue.com/test")
    assert res["title"] == "Test Title"
    assert "Wide leg" in res["content_text"]
    assert res["content_hash"] == content_hash(res["content_text"])
    assert res["language"] in ["en","fa"]

def test_detect_persian():
    assert detect_language("این یک متن فارسی است شلوار گشاد") == "fa"
    assert detect_language("This is English") == "en"
