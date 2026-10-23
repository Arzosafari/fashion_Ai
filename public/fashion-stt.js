/**
 * Fashion STT - Universal Real-Time English Speech-to-Text Module for Fashion Projects
 * Version: 1.0.1
 * 
 * Supports:
 *  - Native Browser Continuous Streaming SpeechRecognition (0ms latency, zero backend load)
 *  - WebSocket PCM Audio Streaming (Vosk / Kaldi backend)
 *  - Fashion Phonetic Normalizer & Domain Lexicon Enhancer
 *  - Client-side Fashion Entity & Filter Extractor (Categories, Garments, Colors, Materials, Sizes, Prices)
 *  - Graceful Permission Error Handling & In-Browser Troubleshooting
 *  - Real-time Audio Level Meter for Waveform / Mic Visualizers
 */

(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.FashionSTT = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {

  // Fashion Phonetic & Common STT Error Fixes
  const PHONETIC_MAP = [
    // Patterns & Materials
    { pattern: /\bhound\s*tooth\b/gi, replacement: 'houndstooth' },
    { pattern: /\bhound['’]?s\s*tooth\b/gi, replacement: 'houndstooth' },
    { pattern: /\bhow['’]?s\s*tooth\b/gi, replacement: 'houndstooth' },
    { pattern: /\btown\s*tooth\b/gi, replacement: 'houndstooth' },
    { pattern: /\bshe\s*fawn\b/gi, replacement: 'chiffon' },
    { pattern: /\bshiff\s*on\b/gi, replacement: 'chiffon' },
    { pattern: /\bcatch\s*near\b/gi, replacement: 'cashmere' },
    { pattern: /\bcash\s*mere\b/gi, replacement: 'cashmere' },
    { pattern: /\bkashmir\b/gi, replacement: 'cashmere' },
    { pattern: /\bkashmere\b/gi, replacement: 'cashmere' },
    { pattern: /\bquarter\s*roy\b/gi, replacement: 'corduroy' },
    { pattern: /\bcord\s*roy\b/gi, replacement: 'corduroy' },
    { pattern: /\bjack\s*card\b/gi, replacement: 'jacquard' },
    { pattern: /\bpep\s*lum\b/gi, replacement: 'peplum' },
    { pattern: /\bpaste\s*lee\b/gi, replacement: 'paisley' },
    { pattern: /\bbook\s*lay\b/gi, replacement: 'bouclé' },
    { pattern: /\bpin\s*stripes?\b/gi, replacement: 'pinstripe' },
    { pattern: /\btie\s*dye\b/gi, replacement: 'tie-dye' },

    // Aesthetics & Styles
    { pattern: /\bout\s*culture\b/gi, replacement: 'haute couture' },
    { pattern: /\bhot\s*couture\b/gi, replacement: 'haute couture' },
    { pattern: /\bold\s*culture\b/gi, replacement: 'haute couture' },
    { pattern: /\bhaut\s*couture\b/gi, replacement: 'haute couture' },
    { pattern: /\bat\s*leisure\b/gi, replacement: 'athleisure' },
    { pattern: /\bathlete\s*sure\b/gi, replacement: 'athleisure' },
    { pattern: /\bballet\s*corps?\b/gi, replacement: 'balletcore' },
    { pattern: /\bballet\s*court\b/gi, replacement: 'balletcore' },
    { pattern: /\bballet\s*core\b/gi, replacement: 'balletcore' },
    { pattern: /\bcottage\s*core\b/gi, replacement: 'cottagecore' },
    { pattern: /\bgorp\s*core\b/gi, replacement: 'gorpcore' },
    { pattern: /\bnorm\s*core\b/gi, replacement: 'normcore' },
    { pattern: /\bmono\s*chrome\b/gi, replacement: 'monochrome' },
    { pattern: /\bover\s*sized?\b/gi, replacement: 'oversized' },
    { pattern: /\bslim\s*fit\b/gi, replacement: 'slim fit' },
    { pattern: /\bwide\s*leg\b/gi, replacement: 'wide leg' },
    { pattern: /\by\s*two\s*k\b/gi, replacement: 'y2k' },

    // Garments
    { pattern: /\bcool\s*lots\b/gi, replacement: 'culottes' },
    { pattern: /\bcoo\s*lots\b/gi, replacement: 'culottes' },
    { pattern: /\bsill\s*wet\b/gi, replacement: 'silhouette' },
    { pattern: /\bturtle\s*neck\b/gi, replacement: 'turtleneck' },
    { pattern: /\bcrop\s*top\b/gi, replacement: 'crop top' },
    { pattern: /\bcross\s*body\b/gi, replacement: 'crossbody' },
    { pattern: /\bslip\s*dress\b/gi, replacement: 'slip dress' },
    { pattern: /\btrench\s*coat\b/gi, replacement: 'trench coat' },
    { pattern: /\bbomber\s*jacket\b/gi, replacement: 'bomber jacket' },
    { pattern: /\bespadreels?\b/gi, replacement: 'espadrilles' },
    { pattern: /\bbuh\s*ray\b/gi, replacement: 'beret' },

    // Brands
    { pattern: /\bsaint\s*lorant\b/gi, replacement: 'Saint Laurent' },
    { pattern: /\bsan\s*laurent\b/gi, replacement: 'Saint Laurent' },
    { pattern: /\byves\s*saint\s*laurent\b/gi, replacement: 'Yves Saint Laurent' },
    { pattern: /\bbotega\b/gi, replacement: 'Bottega Veneta' },
    { pattern: /\bjacque\s*mus\b/gi, replacement: 'Jacquemus' },
    { pattern: /\bbalen\s*ciaga\b/gi, replacement: 'Balenciaga' }
  ];

  // Fashion Entities Reference
  const FASHION_DATA = {
    categories: {
      outerwear: ['coat', 'jacket', 'trench coat', 'blazer', 'bomber jacket', 'cardigan', 'parka', 'puffer', 'windbreaker'],
      tops: ['shirt', 't-shirt', 'tee', 'blouse', 'crop top', 'turtleneck', 'sweater', 'hoodie', 'corset', 'wrap top', 'tank top'],
      bottoms: ['pants', 'trousers', 'jeans', 'skirt', 'shorts', 'culottes', 'cargo pants', 'wide leg trousers', 'leggings'],
      dresses: ['dress', 'slip dress', 'maxi dress', 'midi dress', 'mini dress', 'cocktail dress', 'evening gown', 'wrap dress'],
      footwear: ['shoes', 'boots', 'combat boots', 'sneakers', 'loafers', 'heels', 'sandals', 'espadrilles', 'mules'],
      accessories: ['bag', 'handbag', 'crossbody bag', 'tote bag', 'belt', 'sunglasses', 'scarf', 'hat', 'beret']
    },
    materials: ['cashmere', 'leather', 'silk', 'satin', 'linen', 'denim', 'cotton', 'wool', 'velvet', 'corduroy', 'chiffon', 'jacquard', 'bouclé', 'tulle', 'lace'],
    styles: ['vintage', 'retro', 'minimalist', 'oversized', 'slim fit', 'streetwear', 'quiet luxury', 'grunge', 'y2k', 'romantic', 'tailored', 'casual', 'formal', 'athleisure', 'balletcore', 'cottagecore', 'monochrome'],
    patterns: ['houndstooth', 'plaid', 'floral', 'striped', 'pinstripe', 'polka dot', 'tie-dye', 'animal print', 'leopard', 'paisley', 'herringbone'],
    colors: ['black', 'white', 'ivory', 'cream', 'ecru', 'beige', 'camel', 'tan', 'brown', 'grey', 'charcoal', 'silver', 'gold', 'red', 'burgundy', 'pink', 'blush', 'coral', 'orange', 'rust', 'yellow', 'mustard', 'green', 'emerald', 'olive', 'sage', 'blue', 'navy', 'cobalt', 'sky blue', 'purple', 'lavender', 'lilac'],
    brands: ['Gucci', 'Prada', 'Saint Laurent', 'Chanel', 'Dior', 'Balenciaga', 'Bottega Veneta', 'Jacquemus', 'Loewe', 'Givenchy', 'Versace', 'Miu Miu', 'Burberry', 'Zara']
  };

  const WORD_NUMBERS = {
    'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15,
    'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19,
    'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50,
    'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90,
    'a': 1, 'an': 1
  };

  function parseSpokenNumber(str) {
    if (!str) return null;
    str = str.trim().toLowerCase();
    if (/^\d+(\.\d+)?$/.test(str)) {
      return parseFloat(str);
    }
    const tokens = str.replace(/-/g, ' ').replace(/\band\b/g, ' ').split(/\s+/);
    let total = 0;
    let current = 0;
    let found = false;
    for (const tok of tokens) {
      if (WORD_NUMBERS[tok] !== undefined) {
        current += WORD_NUMBERS[tok];
        found = true;
      } else if (tok === 'hundred') {
        current = (current || 1) * 100;
        found = true;
      } else if (tok === 'thousand') {
        total += (current || 1) * 1000;
        current = 0;
        found = true;
      }
    }
    return found ? (total + current) : null;
  }

  /**
   * Corrects speech recognition transcript for fashion domain.
   */
  function correctFashionText(text) {
    if (!text) return { cleanText: '', corrections: [] };
    let clean = text.trim();
    const corrections = [];

    for (const item of PHONETIC_MAP) {
      if (item.pattern.test(clean)) {
        const matches = clean.match(item.pattern) || [];
        matches.forEach(m => {
          if (m.toLowerCase() !== item.replacement.toLowerCase()) {
            corrections.push({ original: m, corrected: item.replacement });
          }
        });
        clean = clean.replace(item.pattern, item.replacement);
      }
    }
    clean = clean.replace(/\s+/g, ' ').trim();
    return { cleanText: clean, corrections };
  }

  /**
   * Client-side entity extraction.
   */
  function extractEntities(text) {
    const { cleanText, corrections } = correctFashionText(text);
    const lower = ' ' + cleanText.toLowerCase() + ' ';

    const entities = {
      categories: [],
      garments: [],
      colors: [],
      materials: [],
      styles: [],
      patterns: [],
      brands: [],
      size: null,
      price: { min: null, max: null, currency: 'USD' }
    };

    // Garments & Categories
    for (const [cat, garments] of Object.entries(FASHION_DATA.categories)) {
      for (const garment of garments) {
        const regex = new RegExp(`\\b${garment}(s|es)?\\b`, 'i');
        if (regex.test(lower)) {
          if (!entities.garments.includes(garment)) {
            entities.garments.push(garment);
          }
          if (!entities.categories.includes(cat)) {
            entities.categories.push(cat);
          }
        }
      }
    }

    // Colors
    for (const color of FASHION_DATA.colors) {
      const regex = new RegExp(`\\b${color}\\b`, 'i');
      if (regex.test(lower) && !entities.colors.includes(color)) {
        entities.colors.push(color);
      }
    }

    // Materials
    for (const mat of FASHION_DATA.materials) {
      const regex = new RegExp(`\\b${mat}\\b`, 'i');
      if (regex.test(lower) && !entities.materials.includes(mat)) {
        entities.materials.push(mat);
      }
    }

    // Styles
    for (const st of FASHION_DATA.styles) {
      const regex = new RegExp(`\\b${st}\\b`, 'i');
      if (regex.test(lower) && !entities.styles.includes(st)) {
        entities.styles.push(st);
      }
    }

    // Patterns
    for (const pat of FASHION_DATA.patterns) {
      const regex = new RegExp(`\\b${pat}(s)?\\b`, 'i');
      if (regex.test(lower) && !entities.patterns.includes(pat)) {
        entities.patterns.push(pat);
      }
    }

    // Brands
    for (const b of FASHION_DATA.brands) {
      const regex = new RegExp(`\\b${b}\\b`, 'i');
      if (regex.test(lower) && !entities.brands.includes(b)) {
        entities.brands.push(b);
      }
    }

    // Sizes
    const sizeMatches = [
      { regex: /\b(xxs|extra\s+extra\s+small)\b/i, val: 'XXS' },
      { regex: /\b(xs|extra\s+small)\b/i, val: 'XS' },
      { regex: /\b(small|size\s+s)\b/i, val: 'S' },
      { regex: /\b(medium|size\s+m)\b/i, val: 'M' },
      { regex: /\b(large|size\s+l)\b/i, val: 'L' },
      { regex: /\b(xl|extra\s+large)\b/i, val: 'XL' },
      { regex: /\b(xxl)\b/i, val: 'XXL' },
      { regex: /\bsize\s+(\d{1,2})\b/i, format: m => `Size ${m[1]}` }
    ];
    for (const sm of sizeMatches) {
      const m = lower.match(sm.regex);
      if (m) {
        entities.size = sm.format ? sm.format(m) : sm.val;
        break;
      }
    }

    // Price extraction
    const between = lower.match(/between\s+(?:\$)?([a-z0-9\s-]+?)\s+(?:and|to)\s+(?:\$)?([a-z0-9\s-]+?)(?:\s*(?:dollars|bucks|usd))?(?:\s|$)/i);
    if (between) {
      const minVal = parseSpokenNumber(between[1]);
      const maxVal = parseSpokenNumber(between[2]);
      if (minVal !== null && maxVal !== null) {
        entities.price.min = minVal;
        entities.price.max = maxVal;
      }
    } else {
      const under = lower.match(/(?:under|below|less\s+than|up\s+to)\s+(?:\$)?([a-z0-9\s-]+?)(?:\s*(?:dollars|bucks|usd))?(?:\s|$)/i);
      if (under) {
        const maxVal = parseSpokenNumber(under[1]);
        if (maxVal !== null) entities.price.max = maxVal;
      }
      const over = lower.match(/(?:over|above|more\s+than|starting\s+at)\s+(?:\$)?([a-z0-9\s-]+?)(?:\s*(?:dollars|bucks|usd))?(?:\s|$)/i);
      if (over) {
        const minVal = parseSpokenNumber(over[1]);
        if (minVal !== null) entities.price.min = minVal;
      }
    }

    // Search query construction
    const searchTerms = [
      ...entities.brands,
      ...entities.styles,
      ...entities.patterns,
      ...entities.colors,
      ...entities.materials,
      ...entities.garments
    ];
    const searchQuery = searchTerms.length > 0 
      ? Array.from(new Set(searchTerms)).join(' ')
      : cleanText.replace(/^(please\s+)?(find\s+me|show\s+me|search\s+for|looking\s+for|i\s+want)\s+/i, '').trim();

    return {
      rawText: text,
      cleanText,
      corrections,
      entities,
      searchQuery,
      intent: 'search_catalog'
    };
  }

  /**
   * Main FashionSTT Class
   */
  class FashionSTT {
    constructor(options = {}) {
      this.mode = options.mode || 'auto'; // 'browser' | 'websocket' | 'auto'
      this.lang = options.lang || 'en-US';
      this.wsUrl = options.wsUrl || (typeof window !== 'undefined' 
        ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/transcribe`
        : null);

      // Callbacks
      this.onInterim = options.onInterim || (() => {});
      this.onFinal = options.onFinal || (() => {});
      this.onError = options.onError || (() => {});
      this.onStateChange = options.onStateChange || (() => {});
      this.onAudioLevel = options.onAudioLevel || (() => {});

      this.isListening = false;
      this.recognition = null;
      this.socket = null;
      this.audioContext = null;
      this.mediaStream = null;
      this.processor = null;
      this.analyser = null;
      this.animFrameId = null;

      this._init();
    }

    _init() {
      const hasWebSpeech = typeof window !== 'undefined' && 
        ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window);

      if (this.mode === 'auto') {
        this.activeEngine = hasWebSpeech ? 'browser' : 'websocket';
      } else {
        this.activeEngine = this.mode;
      }
    }

    /**
     * Start listening and transcribing in real-time.
     */
    async start() {
      if (this.isListening) return;

      try {
        if (this.activeEngine === 'browser') {
          await this._startBrowserSpeech();
        } else {
          await this._startWebSocketSpeech();
        }

        this.isListening = true;
        this.onStateChange({ status: 'listening', engine: this.activeEngine });
      } catch (err) {
        this.isListening = false;
        this.onError(this._enrichError(err));
        this.onStateChange({ status: 'error', error: err.message });
      }
    }

    /**
     * Stop listening.
     */
    stop() {
      if (!this.isListening) return;
      this.isListening = false;

      if (this.recognition) {
        try { this.recognition.stop(); } catch (e) {}
      }

      if (this.socket && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ action: 'finalize' }));
        setTimeout(() => {
          if (this.socket) {
            this.socket.close();
            this.socket = null;
          }
        }, 300);
      }

      this._cleanupAudio();
      this.onStateChange({ status: 'stopped' });
    }

    _enrichError(err) {
      const msg = (err && err.message) ? err.message.toLowerCase() : '';
      const code = (err && (err.code || err.name)) ? String(err.code || err.name).toLowerCase() : '';

      if (code === 'not-allowed' || code === 'notallowederror' || msg.includes('not-allowed') || msg.includes('not allowed') || msg.includes('permission denied')) {
        const enriched = new Error(
          'Microphone permission was not allowed. In an embedded preview or iframe, browsers block microphone access by default.'
        );
        enriched.code = 'not-allowed';
        enriched.isPermissionError = true;
        enriched.help = 'Click "Open in New Tab" to test live microphone in a standalone window, or test with the preset audio clips below.';
        return enriched;
      }
      return err;
    }

    /**
     * Engine A: Browser Native SpeechRecognition with continuous interim streaming.
     */
    async _startBrowserSpeech() {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SpeechRecognition) {
        throw new Error('Web Speech API is not supported in this browser. Switching to WebSocket mode.');
      }

      this.recognition = new SpeechRecognition();
      this.recognition.continuous = true;
      this.recognition.interimResults = true;
      this.recognition.lang = this.lang;
      this.recognition.maxAlternatives = 1;

      // Start audio level meter gracefully (does not throw if mic is restricted)
      this._startAudioMeter().catch(() => {});

      this.recognition.onresult = (event) => {
        let interimTranscript = '';
        let finalTranscript = '';

        for (let i = event.resultIndex; i < event.results.length; ++i) {
          const transcript = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            finalTranscript += transcript + ' ';
          } else {
            interimTranscript += transcript;
          }
        }

        if (interimTranscript) {
          const { cleanText } = correctFashionText(interimTranscript);
          this.onInterim({
            rawText: interimTranscript,
            cleanText: cleanText,
            isInterim: true
          });
        }

        if (finalTranscript.trim()) {
          const extracted = extractEntities(finalTranscript.trim());
          this.onFinal(extracted);
        }
      };

      this.recognition.onerror = (event) => {
        if (event.error === 'no-speech') return;

        const err = new Error(`Speech recognition error: ${event.error}`);
        err.code = event.error;
        this.onError(this._enrichError(err));
      };

      this.recognition.onend = () => {
        if (this.isListening) {
          try {
            this.recognition.start();
          } catch (e) {
            this.stop();
          }
        }
      };

      try {
        this.recognition.start();
      } catch (err) {
        throw this._enrichError(err);
      }
    }

    /**
     * Engine B: WebSocket PCM Audio Streaming to Vosk Backend.
     */
    async _startWebSocketSpeech() {
      if (!this.wsUrl) {
        throw new Error('WebSocket URL not specified for WebSocket streaming mode.');
      }

      return new Promise(async (resolve, reject) => {
        try {
          this.socket = new WebSocket(this.wsUrl);
          this.socket.binaryType = 'arraybuffer';
        } catch (e) {
          return reject(e);
        }

        this.socket.onopen = async () => {
          try {
            await this._startAudioStreamer();
            resolve();
          } catch (err) {
            reject(this._enrichError(err));
          }
        };

        this.socket.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'partial') {
              this.onInterim({
                rawText: data.text,
                cleanText: data.clean_text,
                isInterim: true
              });
            } else if (data.type === 'final') {
              this.onFinal({
                rawText: data.text,
                cleanText: data.clean_text,
                intent: data.intent,
                entities: data.entities,
                searchQuery: data.search_query,
                corrections: data.corrections,
                confidence: data.confidence
              });
            }
          } catch (e) {
            console.error('Error parsing WebSocket message:', e);
          }
        };

        this.socket.onerror = (err) => {
          const enriched = new Error('WebSocket connection failed');
          this.onError(enriched);
          reject(enriched);
        };

        this.socket.onclose = () => {
          if (this.isListening) {
            this.stop();
          }
        };
      });
    }

    /**
     * Streams PCM 16-bit 16kHz audio over WebSocket
     */
    async _startAudioStreamer() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('Microphone audio API (getUserMedia) not supported in this browser.');
      }

      try {
        this.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      } catch (err) {
        throw this._enrichError(err);
      }

      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this.audioContext = new AudioCtx({ sampleRate: 16000 });

      const source = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 256;

      const bufferSize = 4096;
      this.processor = this.audioContext.createScriptProcessor(bufferSize, 1, 1);

      this.processor.onaudioprocess = (e) => {
        if (!this.isListening || !this.socket || this.socket.readyState !== WebSocket.OPEN) return;
        const inputData = e.inputBuffer.getChannelData(0);
        const pcm16 = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]));
          pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        this.socket.send(pcm16.buffer);
      };

      source.connect(this.analyser);
      this.analyser.connect(this.processor);
      this.processor.connect(this.audioContext.destination);

      this._loopAudioMeter();
    }

    /**
     * Audio visualizer meter helper
     */
    async _startAudioMeter() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
      try {
        this.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        this.audioContext = new AudioCtx();
        const source = this.audioContext.createMediaStreamSource(this.mediaStream);
        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = 256;
        source.connect(this.analyser);
        this._loopAudioMeter();
      } catch (e) {
        // Silently skip if mic is not granted, main recognition will handle error
      }
    }

    _loopAudioMeter() {
      if (!this.analyser) return;
      const dataArray = new Uint8Array(this.analyser.frequencyBinCount);

      const checkVolume = () => {
        if (!this.isListening) return;
        this.analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
          sum += dataArray[i];
        }
        const avg = sum / dataArray.length;
        const normalized = Math.min(1, avg / 128);
        this.onAudioLevel(normalized, dataArray);
        this.animFrameId = requestAnimationFrame(checkVolume);
      };

      this.animFrameId = requestAnimationFrame(checkVolume);
    }

    _cleanupAudio() {
      if (this.animFrameId) cancelAnimationFrame(this.animFrameId);
      if (this.processor) {
        try { this.processor.disconnect(); } catch (e) {}
        this.processor = null;
      }
      if (this.analyser) {
        try { this.analyser.disconnect(); } catch (e) {}
        this.analyser = null;
      }
      if (this.mediaStream) {
        this.mediaStream.getTracks().forEach(track => track.stop());
        this.mediaStream = null;
      }
      if (this.audioContext) {
        try { this.audioContext.close(); } catch (e) {}
        this.audioContext = null;
      }
    }
  }

  // Export static utilities on FashionSTT
  FashionSTT.correctFashionText = correctFashionText;
  FashionSTT.extractEntities = extractEntities;
  FashionSTT.lexicon = FASHION_DATA;

  return FashionSTT;
}));
