# text_masking.py
"""
MLM masking helpers: MLM masks ATTRIBUTE words from the description pool (materials,
patterns, styles, colors, seasons); ITM negatives come from swapping full captions in
the dataset (a strong-enough signal without building fake "negative garments").
"""
from typing import List, Tuple, Optional
from collections import defaultdict
import numpy as np

try:
    from model.kaleido.garment_parse import DF2_CATEGORIES
    from model.kaleido.attribute_vocab import ALLOWED_MASK_WORDS, NEGATIVE_POOL, SEASONS
except ImportError:
    from garment_parse import DF2_CATEGORIES
    from attribute_vocab import ALLOWED_MASK_WORDS, NEGATIVE_POOL, SEASONS


def build_bpe_index(tokenizer) -> Tuple[dict, dict]:
    """Lower-cased id->token table + map from first subword piece -> candidate words."""
    id2tok = {i: t.lower().lstrip("#") for i, t in enumerate(tokenizer.convert_ids_to_tokens(list(range(len(tokenizer)))))}
    piece_index = defaultdict(set)
    for w in list(ALLOWED_MASK_WORDS):
        try:
            pieces = tokenizer.tokenize(w)
        except Exception:
            continue
        if pieces:
            piece_index[pieces[0].lower().lstrip("#")].add(w)
    return id2tok, {k: sorted(v) for k, v in piece_index.items()}


class AttributeTextMasker:
    def __init__(self, tokenizer, mask_prob: float = 0.15, neg_sample_prob: float = 0.5):
        self.tokenizer = tokenizer
        self.mask_prob = mask_prob
        self.neg_sample_prob = neg_sample_prob
        self.id2tok, self._piece_index = build_bpe_index(tokenizer)
        # category names, longest first ("long sleeve top" before "top")
        self.cat_entries = sorted(DF2_CATEGORIES, key=len, reverse=True)
        # season names, longest first (mirrors the 4 season classes of parse_season)
        self.season_entries = sorted(SEASONS, key=len, reverse=True)

    # ------------------------------------------------------------------
    def mask_attribute_words(self, input_ids: np.ndarray,
                             attention_mask: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Mask ATTRIBUTE words (80% [MASK], 10% random word, 10% unchanged)."""
        masked = input_ids.copy()
        labels = np.full_like(input_ids, -100)
        mask_id = self.tokenizer.mask_token_id
        vocab_size = len(self.tokenizer)

        for b in range(input_ids.shape[0]):
            spans = self._find_spans(input_ids[b], attention_mask[b])
            for (s, e, word) in spans:
                if np.random.rand() > self.mask_prob:
                    continue
                labels[b, s:e] = input_ids[b, s:e]
                r = np.random.rand()
                if r < 0.8:
                    masked[b, s:e] = mask_id
                elif r < 0.9:
                    for k in range(s, e):
                        masked[b, k] = np.random.randint(0, vocab_size)
        return masked, labels

    def hide_category(self, ids: np.ndarray, attention_mask: np.ndarray = None) -> np.ndarray:
        """Replace the garment's own category name with [MASK] (train AND inference).

        Without this the model learns "the text says dress -> category = dress"
        and ignores the image; masking keeps category prediction visual.
        """
        out = ids.copy()
        mask_id = self.tokenizer.mask_token_id
        for seq in self.cat_entries:
            try:
                cids = self.tokenizer.convert_tokens_to_ids(self.tokenizer.tokenize(seq))
            except Exception:
                continue
            if not cids or cids[0] is None:
                continue
            L = len(cids)
            for b in range(out.shape[0]):
                n = int(attention_mask[b].sum()) if attention_mask is not None else out.shape[1]
                for s in range(0, max(0, n - L + 1)):
                    if out[b, s:s + L].tolist() == cids:
                        out[b, s:s + L] = mask_id
        return out

    def hide_season(self, ids: np.ndarray, attention_mask: np.ndarray = None) -> np.ndarray:
        """Replace season words with [MASK] (train AND inference).

        Without this the model can read "suitable for winter" from the caption;
        masking forces the season head to look at the image patches instead.
        """
        out = ids.copy()
        mask_id = self.tokenizer.mask_token_id
        for seq in self.season_entries:
            try:
                cids = self.tokenizer.convert_tokens_to_ids(self.tokenizer.tokenize(seq))
            except Exception:
                continue
            if not cids or cids[0] is None:
                continue
            L = len(cids)
            for b in range(out.shape[0]):
                n = int(attention_mask[b].sum()) if attention_mask is not None else out.shape[1]
                for s in range(0, max(0, n - L + 1)):
                    if out[b, s:s + L].tolist() == cids:
                        out[b, s:s + L] = mask_id
        return out

    def make_negatives(self, input_ids: np.ndarray) -> np.ndarray:
        """Swap one attribute word with a word from the negative pool (kept for API compatibility)."""
        neg = input_ids.copy()
        for b in range(input_ids.shape[0]):
            spans = self._find_spans(input_ids[b], None)
            if spans and np.random.rand() < self.neg_sample_prob:
                s, e, word = spans[np.random.randint(len(spans))]
                for cand in NEGATIVE_POOL.get(word, []):
                    try:
                        cids = self.tokenizer.convert_tokens_to_ids(self.tokenizer.tokenize(cand))
                    except Exception:
                        continue
                    if cids and len(cids) == (e - s):
                        neg[b, s:e] = cids
                        break
        return neg

    # ------------------------------------------------------------------
    def _find_spans(self, ids_row: np.ndarray, mask_row: Optional[np.ndarray]) -> List[Tuple[int, int, str]]:
        n = int(mask_row.sum()) if mask_row is not None else len(ids_row)
        toks = [self.id2tok.get(int(i), "") for i in ids_row[:n]]
        spans: List[Tuple[int, int, str]] = []
        for i, tok in enumerate(toks):
            for w in self._piece_index.get(tok, ()):  # 1-2 piece words only; longer compounds skipped deliberately
                try:
                    pieces = self.tokenizer.tokenize(w)
                except Exception:
                    continue
                if len(pieces) > 2:
                    continue
                p0 = pieces[0].lower().lstrip("#")
                if toks[i] != p0:
                    continue
                if len(pieces) == 2:
                    if i + 1 >= len(toks) or toks[i + 1] != pieces[1].lower().lstrip("#"):
                        continue
                    spans.append((i, i + 2, w))
                else:
                    spans.append((i, i + 1, w))
        return spans
