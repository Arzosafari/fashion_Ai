"""
Fashion STT Lexicon & Phonetic Correction Engine
Provides domain-specific vocabulary enhancement, phonetic sound-alike mappings,
and terminology normalization for speech-to-text transcription in fashion.
"""

import re
from typing import Dict, List, Tuple, Set


# Comprehensive Fashion Domain Vocabulary
FASHION_CATEGORIES = {
    "outerwear": ["coat", "jacket", "trench coat", "blazer", "parka", "puffer", "bomber jacket", "windbreaker", "anorak", "cape", "poncho", "duster", "peacoat", "cardigan", "shacket"],
    "tops": ["shirt", "t-shirt", "tee", "blouse", "crop top", "tank top", "halter top", "camisole", "turtleneck", "sweater", "hoodie", "sweatshirt", "corset", "tunic", "polo", "bustier", "bodysuit"],
    "bottoms": ["pants", "trousers", "jeans", "denim", "skirt", "shorts", "culottes", "leggings", "cargo pants", "flare pants", "wide leg trousers", "chinos", "joggers", "sweatpants", "maxi skirt", "mini skirt", "midi skirt", "pleated skirt"],
    "dresses": ["dress", "slip dress", "maxi dress", "midi dress", "mini dress", "cocktail dress", "wrap dress", "bodycon dress", "shirt dress", "sundress", "evening gown", "ballgown", "shift dress", "sheath dress", "kaftan"],
    "footwear": ["shoes", "boots", "ankle boots", "combat boots", "chelsea boots", "knee high boots", "sneakers", "loafers", "heels", "pumps", "sandals", "mules", "slides", "espadrilles", "ballerina flats", "oxfords", "derbies", "stilettos"],
    "accessories": ["bag", "handbag", "tote bag", "crossbody bag", "shoulder bag", "clutch", "backpack", "belt", "sunglasses", "scarf", "hat", "beret", "beanie", "bucket hat", "jewelry", "necklace", "earrings", "bracelet", "ring", "gloves", "headband"],
    "swimwear": ["swimsuit", "bikini", "one piece", "swim trunks", "monokini", "cover up", "sarong"],
    "activewear": ["sports bra", "biker shorts", "leggings", "tracksuit", "gym shorts", "workout top", "athleisure"]
}

FASHION_MATERIALS = [
    "cashmere", "leather", "faux leather", "suede", "silk", "satin", "linen", 
    "denim", "cotton", "wool", "merino wool", "velvet", "corduroy", "chiffon", 
    "tweed", "fleece", "jacquard", "organza", "lace", "shearling", "mohair", 
    "angora", "boucle", "faux fur", "canvas", "mesh", "tulle", "modal", 
    "lyocell", "viscose", "taffeta", "flannel", "poplin", "gabardine", "spandex"
]

FASHION_STYLES = [
    "vintage", "retro", "minimalist", "oversized", "slim fit", "relaxed fit", 
    "cropped", "bohemian", "boho", "preppy", "streetwear", "quiet luxury", 
    "grunge", "y2k", "90s", "avant-garde", "romantic", "tailored", "casual", 
    "formal", "business casual", "athleisure", "balletcore", "cottagecore", 
    "gorpcore", "normcore", "barbiecore", "monochrome", "classic", "edgy", 
    "punk", "utilitarian", "chic", "glamorous", "boho chic"
]

FASHION_PATTERNS = [
    "houndstooth", "plaid", "tartan", "floral", "striped", "pinstripe", 
    "polka dot", "tie-dye", "animal print", "leopard print", "zebra print", 
    "snake print", "paisley", "geometric", "argyle", "herringbone", "chevron", 
    "gingham", "checkered", "camo", "camouflage", "solid", "abstract"
]

FASHION_COLORS = [
    "black", "white", "ivory", "cream", "ecru", "beige", "camel", "tan", 
    "brown", "chocolate", "khaki", "grey", "gray", "charcoal", "silver", 
    "gold", "metallic", "red", "crimson", "burgundy", "maroon", "bordeaux", 
    "wine", "pink", "blush", "rose", "fuchsia", "magenta", "coral", "peach", 
    "orange", "rust", "terracotta", "amber", "yellow", "mustard", "lemon", 
    "green", "emerald", "olive", "sage", "mint", "forest green", "khaki green", 
    "blue", "navy", "royal blue", "cobalt", "sky blue", "baby blue", "denim blue", 
    "turquoise", "teal", "cyan", "purple", "lavender", "lilac", "violet", 
    "plum", "mauve", "indigo", "neon green", "neon pink"
]

FASHION_BRANDS = [
    "Gucci", "Prada", "Saint Laurent", "Yves Saint Laurent", "Chanel", "Dior", 
    "Balenciaga", "Bottega Veneta", "Jacquemus", "Loewe", "Givenchy", "Versace", 
    "Miu Miu", "Burberry", "Hermès", "Ralph Lauren", "Celine", "Fendi", 
    "Valentino", "Alexander McQueen", "Acne Studios", "Maison Margiela", "Loro Piana", 
    "Brunello Cucinelli", "Issey Miyake", "Comme des Garçons", "Rick Owens", 
    "Off-White", "Fear of God", "Zara", "Cos", "Massimo Dutti", "Mango", "Arket"
]

# Map common speech recognition errors, splits, and phonetic substitutions to fashion terms
PHONETIC_CORRECTIONS = {
    # Patterns & Materials
    r"\bhound\s*tooth\b": "houndstooth",
    r"\bhound['’]?s\s*tooth\b": "houndstooth",
    r"\bhow['’]?s\s*tooth\b": "houndstooth",
    r"\btown\s*tooth\b": "houndstooth",
    r"\bshe\s*fawn\b": "chiffon",
    r"\bshiff\s*on\b": "chiffon",
    r"\bshiffon\b": "chiffon",
    r"\bcatch\s*near\b": "cashmere",
    r"\bcash\s*mere\b": "cashmere",
    r"\bkashmir\b": "cashmere",
    r"\bkashmere\b": "cashmere",
    r"\bquarter\s*roy\b": "corduroy",
    r"\bcord\s*roy\b": "corduroy",
    r"\bjack\s*card\b": "jacquard",
    r"\bja\s*guard\b": "jacquard",
    r"\bpep\s*lum\b": "peplum",
    r"\bpepper\s*lamb\b": "peplum",
    r"\bpaste\s*lee\b": "paisley",
    r"\bpace\s*lay\b": "paisley",
    r"\bbook\s*lay\b": "bouclé",
    r"\bherring\s*bone\b": "herringbone",
    r"\bpin\s*stripe\b": "pinstripe",
    r"\bpin\s*stripes\b": "pinstripes",
    r"\btie\s*dye\b": "tie-dye",
    r"\bpolka\s*dots?\b": "polka dot",
    r"\bour\s*guile\b": "argyle",
    r"\bging\s*ham\b": "gingham",
    
    # Styles & Aesthetics
    r"\bout\s*culture\b": "haute couture",
    r"\bhot\s*couture\b": "haute couture",
    r"\bold\s*culture\b": "haute couture",
    r"\bhaut\s*couture\b": "haute couture",
    r"\bhaute\s*culture\b": "haute couture",
    r"\bat\s*leisure\b": "athleisure",
    r"\bathlete\s*sure\b": "athleisure",
    r"\bballet\s*corps?\b": "balletcore",
    r"\bballet\s*court\b": "balletcore",
    r"\bballet\s*core\b": "balletcore",
    r"\bcottage\s*core\b": "cottagecore",
    r"\bgorp\s*core\b": "gorpcore",
    r"\bnorm\s*core\b": "normcore",
    r"\bbarbie\s*core\b": "barbiecore",
    r"\bquiet\s*luxury\b": "quiet luxury",
    r"\bmono\s*chrome\b": "monochrome",
    r"\bover\s*sized?\b": "oversized",
    r"\bslim\s*fit\b": "slim fit",
    r"\bwide\s*leg\b": "wide leg",
    r"\bwide\s*legged\b": "wide leg",
    r"\bwhy\t2\s*k\b": "y2k",
    r"\bwhy\s*two\s*k\b": "y2k",
    r"\by\s*two\s*k\b": "y2k",
    r"\bstreet\s*wear\b": "streetwear",
    r"\bactive\s*wear\b": "activewear",
    r"\bouter\s*wear\b": "outerwear",
    
    # Garments & Cuts
    r"\bcool\s*lots\b": "culottes",
    r"\bcool\s*lot\b": "culottes",
    r"\bcoo\s*lots\b": "culottes",
    r"\bsill\s*wet\b": "silhouette",
    r"\bsilouet\b": "silhouette",
    r"\bturtle\s*neck\b": "turtleneck",
    r"\bcrop\s*top\b": "crop top",
    r"\bcross\s*body\b": "crossbody",
    r"\bslip\s*dress\b": "slip dress",
    r"\btrench\s*coat\b": "trench coat",
    r"\bbomber\s*jacket\b": "bomber jacket",
    r"\btrack\s*suit\b": "tracksuit",
    r"\bbody\s*con\b": "bodycon",
    r"\bbody\s*suit\b": "bodysuit",
    r"\bwind\s*breaker\b": "windbreaker",
    r"\bespa\s*drilles?\b": "espadrilles",
    r"\bespadreels?\b": "espadrilles",
    r"\bbuh\s*ray\b": "beret",
    r"\bcami\s*soul\b": "camisole",
    r"\bcardi\s*gan\b": "cardigan",
    r"\bknee\s*high\b": "knee high",
    r"\bankle\s*boots?\b": "ankle boots",
    
    # Brands
    r"\bsaint\s*lorant\b": "Saint Laurent",
    r"\bsan\s*laurent\b": "Saint Laurent",
    r"\byves\s*saint\s*laurent\b": "Yves Saint Laurent",
    r"\bwhy\s*s\s*l\b": "YSL",
    r"\bbotega\b": "Bottega Veneta",
    r"\bbotega\s*veneta\b": "Bottega Veneta",
    r"\bjacque\s*mus\b": "Jacquemus",
    r"\bjack\s*mousse\b": "Jacquemus",
    r"\bbalen\s*ciaga\b": "Balenciaga",
    r"\bbalen\s*siaga\b": "Balenciaga",
    r"\bcomme\s*de\s*garcon\b": "Comme des Garçons",
    r"\bcomme\s*des\s*garcons\b": "Comme des Garçons",
    r"\bmeg\s*ella\b": "Maison Margiela",
    r"\bmargiela\b": "Maison Margiela",
    r"\bmiu\s*new\b": "Miu Miu",
    r"\bloro\s*piana\b": "Loro Piana",
    r"\blora\s*piana\b": "Loro Piana",
    r"\bralph\s*lauren\b": "Ralph Lauren",
    r"\bcalvin\s*klein\b": "Calvin Klein"
}


def correct_fashion_text(text: str) -> Tuple[str, List[Dict[str, str]]]:
    """
    Applies phonetic corrections, split-word joining, and terminology fixes
    specifically tailored for English fashion speech.
    
    Returns:
        (corrected_text, list_of_applied_corrections)
    """
    if not text:
        return "", []
        
    corrected = text.strip()
    applied_corrections = []
    
    # Run through phonetic regexes
    for pattern, replacement in PHONETIC_CORRECTIONS.items():
        match = re.search(pattern, corrected, flags=re.IGNORECASE)
        if match:
            original_match = match.group(0)
            if original_match.lower() != replacement.lower():
                applied_corrections.append({
                    "original": original_match,
                    "corrected": replacement,
                    "reason": "fashion_lexicon_correction"
                })
            corrected = re.sub(pattern, replacement, corrected, flags=re.IGNORECASE)
            
    # Clean multiple spaces
    corrected = re.sub(r"\s+", " ", corrected).strip()
    return corrected, applied_corrections


def get_all_fashion_terms() -> Set[str]:
    """Returns a flat set of all unique fashion terms across all categories."""
    terms = set()
    for cat_list in FASHION_CATEGORIES.values():
        terms.update(cat_list)
    terms.update(FASHION_MATERIALS)
    terms.update(FASHION_STYLES)
    terms.update(FASHION_PATTERNS)
    terms.update(FASHION_COLORS)
    terms.update(FASHION_BRANDS)
    return terms


def get_fashion_grammar_list() -> List[str]:
    """
    Returns an optimized grammar / vocabulary list suitable for constraining
    Kaldi/Vosk recognizers to prioritize fashion terminology.
    """
    all_terms = sorted(list(get_all_fashion_terms()))
    # Also add essential conversational / search carrier phrases
    carrier_words = [
        "show", "me", "find", "search", "looking", "for", "i", "want", "need",
        "under", "dollars", "bucks", "price", "size", "small", "medium", "large",
        "extra", "in", "with", "and", "a", "an", "the", "for", "summer", "winter",
        "fall", "spring", "party", "wedding", "office", "casual", "sale", "cheap",
        "expensive", "luxury", "budget", "filter", "sort", "by", "recommend", "outfit"
    ]
    words = set(carrier_words)
    for term in all_terms:
        for w in term.lower().split():
            words.add(w)
    return sorted(list(words))
