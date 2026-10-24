from __future__ import annotations
import hashlib

def content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

def is_exact_duplicate(hash_a: str, hash_b: str) -> bool:
    return hash_a == hash_b

def simhash_approx(text: str) -> int:
    # Simple simhash placeholder: use hash of normalized words
    words = text.lower().split()
    # Use Python hash of each word mod 64 bits
    import hashlib
    v = [0]*64
    for w in words[:200]:
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        for i in range(64):
            bit = (h >> i) & 1
            v[i] += 1 if bit else -1
    fingerprint=0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= 1 << i
    return fingerprint

def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")

def is_near_duplicate(fp1: int, fp2: int, threshold: int = 3) -> bool:
    return hamming(fp1, fp2) <= threshold
