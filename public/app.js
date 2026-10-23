/**
 * Fashion AI — User Request Understanding Module Frontend Controller
 * Unified Voice & Text Input, Editable Transcript Review, Multi-turn Context, and Structured JSON Viewer.
 */

document.addEventListener('DOMContentLoaded', () => {
  // DOM Elements
  const textInput = document.getElementById('textInput');
  const sendBtn = document.getElementById('sendBtn');
  const micBtn = document.getElementById('micBtn');
  const chatStream = document.getElementById('chatStream');
  const resetSessionBtn = document.getElementById('resetSessionBtn');
  const toggleTtsBtn = document.getElementById('toggleTtsBtn');
  const ttsIcon = document.getElementById('ttsIcon');
  const ttsLabel = document.getElementById('ttsLabel');
  const openNewTabBtn = document.getElementById('openNewTabBtn');
  const autoSubmitCheck = document.getElementById('autoSubmitCheck');

  // Voice Review & Editor Elements
  const voiceReviewBox = document.getElementById('voiceReviewBox');
  const editableTranscript = document.getElementById('editableTranscript');
  const recordingIndicator = document.getElementById('recordingIndicator');
  const cancelVoiceBtn = document.getElementById('cancelVoiceBtn');
  const stopRecordBtn = document.getElementById('stopRecordBtn');
  const submitVoiceBtn = document.getElementById('submitVoiceBtn');
  const visualizerCanvas = document.getElementById('visualizerCanvas');

  // Permission Banner Elements
  const permissionBanner = document.getElementById('permissionBanner');
  const bannerNewTabBtn = document.getElementById('bannerNewTabBtn');
  const bannerTrySampleBtn = document.getElementById('bannerTrySampleBtn');
  const closeBannerBtn = document.getElementById('closeBannerBtn');

  // File Upload Elements
  const dropzone = document.getElementById('dropzone');
  const fileUploadInput = document.getElementById('fileUploadInput');

  // Feature Summary Elements
  const valIntentType = document.getElementById('valIntentType');
  const valIntentDesc = document.getElementById('valIntentDesc');
  const valOccasion = document.getElementById('valOccasion');
  const valFormality = document.getElementById('valFormality');
  const valOccasionSource = document.getElementById('valOccasionSource');
  const valTime = document.getElementById('valTime');
  const valLocation = document.getElementById('valLocation');
  const garmentIncludeChips = document.getElementById('garmentIncludeChips');
  const garmentExcludeChips = document.getElementById('garmentExcludeChips');
  const colorPrefChips = document.getElementById('colorPrefChips');
  const colorExcludeChips = document.getElementById('colorExcludeChips');
  const styleChips = document.getElementById('styleChips');
  const functionalChips = document.getElementById('functionalChips');
  const constraintRow = document.getElementById('constraintRow');
  const constraintChips = document.getElementById('constraintChips');
  const clarificationBanner = document.getElementById('clarificationBanner');
  const clarificationQuestionText = document.getElementById('clarificationQuestionText');
  const confidenceBadge = document.getElementById('confidenceBadge');
  const locationSettingInput = document.getElementById('locationSettingInput');
  const weatherStatusPill = document.getElementById('weatherStatusPill');
  const valWeatherLocation = document.getElementById('valWeatherLocation');
  const valWeatherLocSource = document.getElementById('valWeatherLocSource');
  const valWeatherWindow = document.getElementById('valWeatherWindow');
  const valWeatherCacheTag = document.getElementById('valWeatherCacheTag');
  const valWeatherTemp = document.getElementById('valWeatherTemp');
  const valWeatherFeels = document.getElementById('valWeatherFeels');
  const valWeatherCondition = document.getElementById('valWeatherCondition');
  const valWeatherWind = document.getElementById('valWeatherWind');
  const weatherUnavailableNote = document.getElementById('weatherUnavailableNote');
  const jsonOutput = document.getElementById('jsonOutput');
  const copyJsonBtn = document.getElementById('copyJsonBtn');
  const ttsAudioPlayer = document.getElementById('ttsAudioPlayer');

  // State
  let sessionId = 'session_' + Math.random().toString(36).substring(2, 10);
  let isRecording = false;
  let isProcessing = false;
  let ttsEnabled = true;
  let rawVoiceTranscript = '';
  let canvasCtx = visualizerCanvas.getContext('2d');
  let currentAudioLevel = 0;
  let sttInstance = null;
  let activeJsonTab = 'request';
  let latestPayloads = {
    request: null,
    weather: null,
    combined: null
  };

  // Initialize Canvas
  function resizeCanvas() {
    visualizerCanvas.width = visualizerCanvas.parentElement.clientWidth || 460;
    visualizerCanvas.height = 48;
  }
  resizeCanvas();
  window.addEventListener('resize', resizeCanvas);

  // New Tab Handler
  function openInNewTab() {
    window.open(window.location.href, '_blank');
  }
  if (openNewTabBtn) openNewTabBtn.addEventListener('click', openInNewTab);
  if (bannerNewTabBtn) bannerNewTabBtn.addEventListener('click', openInNewTab);
  if (closeBannerBtn) {
    closeBannerBtn.addEventListener('click', () => {
      permissionBanner.style.display = 'none';
    });
  }
  if (bannerTrySampleBtn) {
    bannerTrySampleBtn.addEventListener('click', () => {
      permissionBanner.style.display = 'none';
      const prompt = document.querySelector('.prompt-chip');
      if (prompt) prompt.click();
    });
  }

  // Toggle TTS Voice Feedback
  toggleTtsBtn.addEventListener('click', () => {
    ttsEnabled = !ttsEnabled;
    if (ttsEnabled) {
      toggleTtsBtn.classList.add('active');
      ttsIcon.textContent = '🔊';
      ttsLabel.textContent = 'Voice Feedback: ON';
    } else {
      toggleTtsBtn.classList.remove('active');
      ttsIcon.textContent = '🔇';
      ttsLabel.textContent = 'Voice Feedback: OFF';
      stopAudioPlayback();
    }
  });

  // Stop any active audio playback
  function stopAudioPlayback() {
    if (window.speechSynthesis && window.speechSynthesis.speaking) {
      window.speechSynthesis.cancel();
    }
    if (ttsAudioPlayer && !ttsAudioPlayer.paused) {
      ttsAudioPlayer.pause();
      ttsAudioPlayer.currentTime = 0;
    }
  }

  // Play Spoken Audio Feedback (Web SpeechSynthesis with /api/tts fallback)
  function playSpokenFeedback(text, ttsUrl) {
    if (!ttsEnabled || !text) return;
    stopAudioPlayback();

    if ('speechSynthesis' in window) {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'en-US';
      utterance.rate = 1.0;
      utterance.pitch = 1.0;
      window.speechSynthesis.speak(utterance);
    } else if (ttsUrl) {
      ttsAudioPlayer.src = ttsUrl;
      ttsAudioPlayer.play().catch(e => console.warn('Audio playback blocked:', e));
    }
  }

  // Initialize STT Engine
  function initSTT() {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/transcribe`;

    sttInstance = new FashionSTT({
      mode: 'auto',
      wsUrl: wsUrl,
      lang: 'en-US',
      onInterim: (data) => {
        editableTranscript.value = data.cleanText;
        rawVoiceTranscript = data.rawText;
        recordingIndicator.textContent = 'Speaking...';
      },
      onFinal: (result) => {
        editableTranscript.value = result.cleanText;
        rawVoiceTranscript = result.rawText;
        recordingIndicator.textContent = 'Speech captured';

        // Auto-submit if enabled
        if (autoSubmitCheck.checked && result.cleanText.trim()) {
          setTimeout(() => {
            if (isRecording) stopRecording();
            submitVoiceTranscript();
          }, 600);
        }
      },
      onError: (err) => {
        console.warn('STT Error:', err);
        stopRecording();
        if (err.isPermissionError || err.code === 'not-allowed') {
          permissionBanner.style.display = 'flex';
          addChatMessage('system', '⚠️ Microphone access is not allowed in this preview frame. Please open in a standalone tab or type below.');
        } else {
          addChatMessage('system', `⚠️ Speech Recognition error: ${err.message}`);
        }
      },
      onStateChange: (state) => {
        if (state.status === 'listening') {
          isRecording = true;
          micBtn.classList.add('recording');
          voiceReviewBox.style.display = 'block';
          stopRecordBtn.style.display = 'inline-block';
          recordingIndicator.textContent = 'Listening...';
        } else if (state.status === 'stopped') {
          isRecording = false;
          micBtn.classList.remove('recording');
          stopRecordBtn.style.display = 'none';
        }
      },
      onAudioLevel: (normalizedLevel) => {
        currentAudioLevel = normalizedLevel;
      }
    });
  }
  initSTT();

  // Waveform Visualizer Loop
  function drawVisualizer() {
    const w = visualizerCanvas.width;
    const h = visualizerCanvas.height;
    canvasCtx.clearRect(0, 0, w, h);

    const numBars = 36;
    const barWidth = (w / numBars) - 2;
    const centerY = h / 2;
    const baseActivity = isRecording ? Math.max(0.18, currentAudioLevel) : 0.03;
    const time = Date.now() * 0.005;

    for (let i = 0; i < numBars; i++) {
      const x = i * (barWidth + 2);
      const wave = Math.sin(time + i * 0.25) * Math.cos(time * 0.7 + i * 0.1);
      const barHeight = Math.max(3, Math.abs(wave) * 16 * baseActivity + (baseActivity * (h - 8)));

      const grad = canvasCtx.createLinearGradient(0, centerY - barHeight / 2, 0, centerY + barHeight / 2);
      if (isRecording) {
        grad.addColorStop(0, '#e6c564');
        grad.addColorStop(1, '#ff758c');
      } else {
        grad.addColorStop(0, 'rgba(230, 197, 100, 0.2)');
        grad.addColorStop(1, 'rgba(255, 255, 255, 0.05)');
      }

      canvasCtx.fillStyle = grad;
      canvasCtx.beginPath();
      canvasCtx.roundRect(x, centerY - barHeight / 2, barWidth, barHeight, 2);
      canvasCtx.fill();
    }

    currentAudioLevel *= 0.88;
    requestAnimationFrame(drawVisualizer);
  }
  drawVisualizer();

  // Mic Button Toggle
  micBtn.addEventListener('click', () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  });

  function startRecording() {
    stopAudioPlayback();
    editableTranscript.value = '';
    rawVoiceTranscript = '';
    voiceReviewBox.style.display = 'block';
    sttInstance.start();
  }

  function stopRecording() {
    if (sttInstance) sttInstance.stop();
    isRecording = false;
    micBtn.classList.remove('recording');
    recordingIndicator.textContent = 'Ready for review';
    stopRecordBtn.style.display = 'none';
  }

  stopRecordBtn.addEventListener('click', stopRecording);

  cancelVoiceBtn.addEventListener('click', () => {
    stopRecording();
    editableTranscript.value = '';
    rawVoiceTranscript = '';
    voiceReviewBox.style.display = 'none';
  });

  submitVoiceBtn.addEventListener('click', submitVoiceTranscript);

  function submitVoiceTranscript() {
    const text = editableTranscript.value.trim();
    if (!text) return;
    stopRecording();
    voiceReviewBox.style.display = 'none';
    submitRequest(text, 'voice', rawVoiceTranscript);
    editableTranscript.value = '';
    rawVoiceTranscript = '';
  }

  // Text Input Submit
  sendBtn.addEventListener('click', () => {
    const text = textInput.value.trim();
    if (!text || isProcessing) return;
    submitRequest(text, 'text');
    textInput.value = '';
  });

  textInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const text = textInput.value.trim();
      if (!text || isProcessing) return;
      submitRequest(text, 'text');
      textInput.value = '';
    }
  });

  // Prompt Chips Click
  document.querySelectorAll('.prompt-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const text = chip.dataset.text;
      textInput.value = text;
      submitRequest(text, 'text');
    });
  });

  const NON_GEO_VENUES = new Set([
    'outdoor', 'outdoors', 'indoor', 'indoors', 'beach', 'coast',
    'beachside', 'office', 'workplace', 'campus', 'university',
    'rooftop', 'restaurant', 'home', 'venue'
  ]);

  /**
   * When the backend server runs inside a firewall-restricted container that cannot reach
   * `api.open-meteo.com` directly (`status === 'network_error'`), fetches live keyless
   * Open-Meteo JSON from the browser and sends it to `POST /api/weather/resolve` so the
   * Python backend validates, normalizes, and caches it canonically.
   */
  async function relayLiveOpenMeteoIfSandboxed(structured, weather, explicitFallbackLoc) {
    if (!weather || weather.available || weather.status !== 'network_error') {
      return { weather, combined: latestPayloads.combined };
    }

    const reqLoc = structured && structured.location && structured.location.value
      ? structured.location.value.trim()
      : null;
    const hasGeoReqLoc = reqLoc && !NON_GEO_VENUES.has(reqLoc.toLowerCase());
    const locSource = weather.location
      ? weather.location.source
      : (hasGeoReqLoc ? 'request' : 'settings');
    const candidateName = weather.location
      ? weather.location.name
      : (hasGeoReqLoc ? reqLoc : explicitFallbackLoc);

    const dateTarget = (structured && structured.time && structured.time.source === 'explicit')
      ? (structured.time.resolved || structured.time.expression)
      : (weather.forecast_for || null);

    if (weatherStatusPill) {
      weatherStatusPill.className = 'weather-status-pill available';
      weatherStatusPill.textContent = 'Fetching Live Weather...';
    }
    if (weatherUnavailableNote) {
      weatherUnavailableNote.style.display = 'none';
    }

    try {
      let lat = weather.location ? weather.location.latitude : null;
      let lon = weather.location ? weather.location.longitude : null;
      let geocodingPayload = null;

      // Step 1: If city was outside built-in gazetteer, resolve coordinates via Open-Meteo Geocoding API
      if ((lat === null || lon === null) && candidateName) {
        const geoUrl = `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(candidateName)}&count=1&language=en&format=json`;
        const geoRes = await fetch(geoUrl);
        if (geoRes.ok) {
          geocodingPayload = await geoRes.json();
          if (geocodingPayload && Array.isArray(geocodingPayload.results) && geocodingPayload.results.length > 0) {
            lat = geocodingPayload.results[0].latitude;
            lon = geocodingPayload.results[0].longitude;
          } else {
            // Unknown place -> let Python backend return canonical `invalid_location`
            const invalidRes = await fetch('/api/weather/resolve', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                session_id: sessionId,
                location: candidateName,
                location_source: locSource,
                date_or_time: dateTarget,
                geocoding_payload: geocodingPayload || { results: [] }
              })
            });
            if (invalidRes.ok) {
              const parsedInvalid = await invalidRes.json();
              return {
                weather: parsedInvalid.weather_context,
                combined: parsedInvalid.recommendation_context || latestPayloads.combined
              };
            }
          }
        }
      }

      if (lat === null || lon === null) {
        return { weather, combined: latestPayloads.combined };
      }

      // Step 2: Query live Open-Meteo Forecast or Current Weather API
      let forecastIsoDate = null;
      if (weather.mode === 'forecast' || dateTarget) {
        const rawWindow = weather.forecast_for || dateTarget || '';
        const isoMatch = String(rawWindow).match(/^(\d{4}-\d{2}-\d{2})/);
        if (isoMatch) {
          forecastIsoDate = isoMatch[1];
        }
      }

      let openMeteoUrl;
      if (forecastIsoDate) {
        openMeteoUrl =
          `https://api.open-meteo.com/v1/forecast?latitude=${encodeURIComponent(lat)}&longitude=${encodeURIComponent(lon)}` +
          `&start_date=${encodeURIComponent(forecastIsoDate)}&end_date=${encodeURIComponent(forecastIsoDate)}` +
          `&hourly=temperature_2m,apparent_temperature,relative_humidity_2m,precipitation_probability,precipitation,wind_speed_10m,weather_code` +
          `&daily=temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,weather_code` +
          `&timezone=auto`;
      } else {
        openMeteoUrl =
          `https://api.open-meteo.com/v1/forecast?latitude=${encodeURIComponent(lat)}&longitude=${encodeURIComponent(lon)}` +
          `&current=temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,wind_speed_10m,weather_code` +
          `&timezone=auto`;
      }

      const providerHttp = await fetch(openMeteoUrl);
      if (!providerHttp.ok) {
        return { weather, combined: latestPayloads.combined };
      }
      const providerPayload = await providerHttp.json();

      // Step 3: Submit raw Open-Meteo payload to Python backend for schema validation & TTL caching
      const resolveRes = await fetch('/api/weather/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          location: candidateName,
          latitude: lat,
          longitude: lon,
          location_source: locSource,
          date_or_time: dateTarget,
          geocoding_payload: geocodingPayload,
          provider_payload: providerPayload
        })
      });

      if (!resolveRes.ok) {
        return { weather, combined: latestPayloads.combined };
      }

      const resolved = await resolveRes.json();
      return {
        weather: resolved.weather_context,
        combined: resolved.recommendation_context || latestPayloads.combined
      };
    } catch (relayErr) {
      console.warn('Live Open-Meteo relay unavailable:', relayErr);
      return { weather, combined: latestPayloads.combined };
    }
  }

  // Refresh Weather Context immediately when user updates optional header Location setting
  async function refreshWeatherForLocationSetting() {
    if (!locationSettingInput) return;
    const locVal = locationSettingInput.value.trim();
    const activeReq = latestPayloads.request;

    // Do not override an explicit city that came directly from the active request utterance
    if (activeReq && activeReq.location && activeReq.location.value && !NON_GEO_VENUES.has(activeReq.location.value.toLowerCase())) {
      return;
    }

    const targetTime = (activeReq && activeReq.time && activeReq.time.source === 'explicit')
      ? (activeReq.time.resolved || activeReq.time.expression)
      : null;

    const params = new URLSearchParams();
    if (locVal) params.set('location', locVal);
    if (targetTime) params.set('date_or_time', targetTime);

    try {
      const res = await fetch(`/api/weather?${params.toString()}`);
      if (!res.ok) return;
      let weather = await res.json();
      if (locVal && weather.location) {
        weather.location.source = 'settings';
      }

      const relayed = await relayLiveOpenMeteoIfSandboxed(activeReq, weather, locVal || null);
      latestPayloads.weather = relayed.weather;
      if (activeReq) {
        latestPayloads.combined = relayed.combined || {
          request_context: activeReq,
          weather_context: relayed.weather
        };
      }
      renderWeatherContext(relayed.weather);
      renderActiveJsonTab();
    } catch (err) {
      console.warn('Weather setting refresh failed:', err);
    }
  }

  if (locationSettingInput) {
    let locDebounce = null;
    locationSettingInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        clearTimeout(locDebounce);
        refreshWeatherForLocationSetting();
      }
    });
    locationSettingInput.addEventListener('change', () => {
      clearTimeout(locDebounce);
      refreshWeatherForLocationSetting();
    });
    locationSettingInput.addEventListener('input', () => {
      clearTimeout(locDebounce);
      locDebounce = setTimeout(refreshWeatherForLocationSetting, 650);
    });
  }

  // Core Request Submission Function (Unified Pipeline)
  async function submitRequest(text, inputMethod = 'text', rawTranscript = null) {
    if (isProcessing) return;
    isProcessing = true;
    sendBtn.disabled = true;

    // Render User Message
    addChatMessage('user', text, inputMethod);

    try {
      const explicitFallbackLocation = locationSettingInput && locationSettingInput.value.trim()
        ? locationSettingInput.value.trim()
        : null;

      const response = await fetch('/api/understand', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: text,
          session_id: sessionId,
          input_method: inputMethod,
          raw_transcript: rawTranscript,
          location: explicitFallbackLocation
        })
      });

      if (!response.ok) {
        throw new Error(`API returned status ${response.status}`);
      }

      const data = await response.json();
      sessionId = data.session_id;

      // Render Assistant Response
      addChatMessage('assistant', data.assistant_response, null, data.tts_url);

      // Play Audio TTS
      playSpokenFeedback(data.assistant_response, data.tts_url);

      // Render user request features immediately
      latestPayloads.request = data.structured_data || null;
      latestPayloads.combined = data.recommendation_context || null;
      renderStructuredFeatures(data.structured_data);

      // Resolve weather (uses direct backend response when online, or live Open-Meteo HTTPS relay if sandboxed)
      const resolvedWeather = await relayLiveOpenMeteoIfSandboxed(
        data.structured_data,
        data.weather_context,
        explicitFallbackLocation
      );
      latestPayloads.weather = resolvedWeather.weather || data.weather_context || null;
      latestPayloads.combined = resolvedWeather.combined || data.recommendation_context || null;

      renderWeatherContext(latestPayloads.weather);
      renderActiveJsonTab();

    } catch (err) {
      console.error('Request understanding error:', err);
      addChatMessage('system', `Error processing request: ${err.message}`);
    } finally {
      isProcessing = false;
      sendBtn.disabled = false;
      textInput.focus();
    }
  }

  // Render Chat Message in Dialogue Stream
  function addChatMessage(role, content, method = null, ttsUrl = null) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `chat-message ${role}-message`;

    let avatar = '👗';
    let label = 'Fashion AI';
    if (role === 'user') {
      avatar = '👤';
      label = 'You';
    } else if (role === 'system') {
      avatar = '⚠️';
      label = 'System';
    }

    const methodTag = method ? `<span class="method-tag">${method === 'voice' ? '🎙️ Voice' : '⌨️ Text'}</span>` : '';
    const audioBtn = (role === 'assistant' && ttsUrl) ? `
      <button class="btn-play-tts" onclick="window.playSingleTts('${escapeJsString(content)}', '${ttsUrl}')">
        <span>🔊 Play Spoken Confirmation</span>
      </button>
    ` : '';

    msgDiv.innerHTML = `
      <div class="msg-avatar">${avatar}</div>
      <div class="msg-bubble">
        <p>${escapeHtml(content)}</p>
        <div class="msg-meta">
          <span>${label}</span>
          ${methodTag}
        </div>
        ${audioBtn}
      </div>
    `;

    chatStream.appendChild(msgDiv);
    chatStream.scrollTop = chatStream.scrollHeight;
  }

  window.playSingleTts = (text, ttsUrl) => {
    playSpokenFeedback(text, ttsUrl);
  };

  // Render Structured Features into Summary Grid & JSON Viewer
  function renderStructuredFeatures(data) {
    if (!data) return;

    // Intent
    valIntentType.textContent = data.intent.type;
    valIntentDesc.textContent = data.intent.description;

    // Occasion & Formality
    valOccasion.textContent = data.occasion.value || 'None';
    valFormality.textContent = data.occasion.formality || 'None';
    valOccasionSource.textContent = data.occasion.source || 'unknown';

    // Time & Location
    valTime.textContent = data.time.expression 
      ? `${data.time.expression} (${data.time.resolved || 'unresolved'})`
      : 'None';
    valLocation.textContent = data.location.value || 'None';

    // Garments Include & Exclude
    renderBadgeChips(garmentIncludeChips, data.garment_preferences.include, 'chip-include');
    renderBadgeChips(garmentExcludeChips, data.garment_preferences.exclude, 'chip-exclude');

    // Colors Preferred & Excluded
    renderBadgeChips(colorPrefChips, data.colors.preferred, 'chip-pref-color');
    renderBadgeChips(colorExcludeChips, data.colors.excluded, 'chip-exclude');

    // Styles
    const styleVals = (data.style_preferences || []).map(s => s.value);
    renderBadgeChips(styleChips, styleVals, 'chip-style-item');

    // Functional Requirements
    renderBadgeChips(functionalChips, data.functional_requirements, 'chip-functional-item');

    // Constraints
    if (data.constraints && data.constraints.length > 0) {
      constraintRow.style.display = 'flex';
      renderBadgeChips(constraintChips, data.constraints, 'chip-constraint-item');
    } else {
      constraintRow.style.display = 'none';
      constraintChips.innerHTML = '';
    }

    // Clarification Banner
    if (data.clarification_needed && data.clarification_question) {
      clarificationBanner.style.display = 'flex';
      clarificationQuestionText.textContent = data.clarification_question;
    } else {
      clarificationBanner.style.display = 'none';
    }

    // Confidence
    const conf = Math.round((data.confidence_score || 0.9) * 100);
    confidenceBadge.textContent = `Confidence: ${conf}%`;
  }

  function renderWeatherContext(weather) {
    if (!weather || !weatherStatusPill) return;

    if (weather.available) {
      weatherStatusPill.className = 'weather-status-pill available';
      weatherStatusPill.textContent = weather.mode === 'forecast' ? 'Forecast Ready' : 'Current Weather Ready';

      valWeatherLocation.textContent = weather.location
        ? `${weather.location.name}${weather.location.country ? ', ' + weather.location.country : ''}`
        : 'Resolved';
      valWeatherLocSource.textContent = weather.location ? weather.location.source : 'request';

      valWeatherWindow.textContent = weather.mode === 'forecast'
        ? `forecast (${weather.forecast_for || 'scheduled'})`
        : `current (${weather.observed_at || 'live'})`;
      valWeatherCacheTag.textContent = weather.cached ? 'cached' : 'fresh';

      valWeatherTemp.textContent = weather.temperature
        ? `${weather.temperature.value}°${weather.temperature.unit}`
        : '—';

      if (weather.feels_like) {
        valWeatherFeels.textContent = `Feels like: ${weather.feels_like.value}°${weather.feels_like.unit}`;
      } else if (weather.temperature_range) {
        valWeatherFeels.textContent = `Range: ${weather.temperature_range.min}°–${weather.temperature_range.max}°${weather.temperature_range.unit}`;
      } else {
        valWeatherFeels.textContent = 'Feels like: N/A';
      }

      valWeatherCondition.textContent = weather.condition
        ? weather.condition.replace(/_/g, ' ')
        : 'Reported';

      const windPart = weather.wind_speed ? `${weather.wind_speed.value} ${weather.wind_speed.unit}` : 'N/A';
      const precipPart = weather.precipitation_probability !== null && weather.precipitation_probability !== undefined
        ? `${weather.precipitation_probability}% prob`
        : (weather.precipitation ? `${weather.precipitation.value} ${weather.precipitation.unit}` : 'N/A');
      valWeatherWind.textContent = `Wind: ${windPart} • Precip: ${precipPart}`;
      weatherUnavailableNote.style.display = 'none';
      weatherUnavailableNote.textContent = '';
    } else {
      weatherStatusPill.className = 'weather-status-pill unavailable';
      weatherStatusPill.textContent = `Unavailable (${weather.status || 'unavailable'})`;

      valWeatherLocation.textContent = weather.location ? weather.location.name : 'None';
      valWeatherLocSource.textContent = weather.location ? weather.location.source : 'none';
      valWeatherWindow.textContent = weather.forecast_for || weather.mode || 'None';
      valWeatherCacheTag.textContent = 'unavailable';
      valWeatherTemp.textContent = '—';
      valWeatherFeels.textContent = 'Feels like: —';
      valWeatherCondition.textContent = '—';
      valWeatherWind.textContent = 'Wind: — • Precip: —';

      if (weather.message) {
        weatherUnavailableNote.style.display = 'block';
        weatherUnavailableNote.textContent = weather.message;
      } else {
        weatherUnavailableNote.style.display = 'none';
      }
    }
  }

  function renderActiveJsonTab() {
    const selected = latestPayloads[activeJsonTab];
    if (!selected) {
      jsonOutput.innerHTML = `<code>{\n  "status": "awaiting_input"\n}</code>`;
      return;
    }
    jsonOutput.innerHTML = `<code>${escapeHtml(JSON.stringify(selected, null, 2))}</code>`;
  }

  document.querySelectorAll('.json-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.json-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeJsonTab = btn.dataset.view || 'request';
      renderActiveJsonTab();
    });
  });

  function renderBadgeChips(container, items, className) {
    if (!items || items.length === 0) {
      container.innerHTML = '<span class="chip-empty">None</span>';
      return;
    }
    container.innerHTML = items.map(item => `
      <span class="badge-chip ${className}">${escapeHtml(item)}</span>
    `).join('');
  }

  // Copy JSON Button
  copyJsonBtn.addEventListener('click', () => {
    const text = jsonOutput.innerText;
    navigator.clipboard.writeText(text).then(() => {
      const orig = copyJsonBtn.textContent;
      copyJsonBtn.textContent = '✅ Copied!';
      setTimeout(() => copyJsonBtn.textContent = orig, 1500);
    });
  });

  // Reset Session
  resetSessionBtn.addEventListener('click', async () => {
    stopAudioPlayback();
    try {
      await fetch(`/api/session/reset?session_id=${sessionId}`, { method: 'POST' });
    } catch (e) {}

    sessionId = 'session_' + Math.random().toString(36).substring(2, 10);
    chatStream.innerHTML = `
      <div class="chat-message assistant-message">
        <div class="msg-avatar">👗</div>
        <div class="msg-bubble">
          <p>Session reset! I am ready for a new fashion request.</p>
          <span class="msg-tip">What occasion or outfit would you like to plan?</span>
        </div>
      </div>
    `;
    clearSummaryDisplay();
  });

  function clearSummaryDisplay() {
    valIntentType.textContent = 'outfit_recommendation';
    valIntentDesc.textContent = 'Waiting for request...';
    valOccasion.textContent = 'None';
    valFormality.textContent = 'None';
    valOccasionSource.textContent = 'unknown';
    valTime.textContent = 'None';
    valLocation.textContent = 'None';
    garmentIncludeChips.innerHTML = '<span class="chip-empty">None</span>';
    garmentExcludeChips.innerHTML = '<span class="chip-empty">None</span>';
    colorPrefChips.innerHTML = '<span class="chip-empty">None</span>';
    colorExcludeChips.innerHTML = '<span class="chip-empty">None</span>';
    styleChips.innerHTML = '<span class="chip-empty">None</span>';
    functionalChips.innerHTML = '<span class="chip-empty">None</span>';
    constraintRow.style.display = 'none';
    clarificationBanner.style.display = 'none';
    latestPayloads = { request: null, weather: null, combined: null };
    if (weatherStatusPill) {
      weatherStatusPill.className = 'weather-status-pill unavailable';
      weatherStatusPill.textContent = 'Awaiting Request';
      valWeatherLocation.textContent = 'None';
      valWeatherLocSource.textContent = 'none';
      valWeatherWindow.textContent = 'None';
      valWeatherCacheTag.textContent = 'live';
      valWeatherTemp.textContent = '—';
      valWeatherFeels.textContent = 'Feels like: —';
      valWeatherCondition.textContent = '—';
      valWeatherWind.textContent = 'Wind: — • Precip: —';
      weatherUnavailableNote.style.display = 'none';
    }
    jsonOutput.innerHTML = `<code>{\n  "status": "awaiting_input"\n}</code>`;
  }

  // Audio File Upload Dropzone
  dropzone.addEventListener('click', () => fileUploadInput.click());

  dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.style.borderColor = 'var(--gold-primary)';
  });

  dropzone.addEventListener('dragleave', () => {
    dropzone.style.borderColor = 'var(--border-subtle)';
  });

  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.style.borderColor = 'var(--border-subtle)';
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleAudioFileUpload(e.dataTransfer.files[0]);
    }
  });

  fileUploadInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleAudioFileUpload(e.target.files[0]);
    }
  });

  async function handleAudioFileUpload(file) {
    addChatMessage('system', `Transcribing uploaded audio: ${file.name}...`);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/transcribe', {
        method: 'POST',
        body: formData
      });
      if (!res.ok) throw new Error('Audio transcription failed');
      const data = await res.json();

      // Open in review editor so user can verify before sending
      voiceReviewBox.style.display = 'block';
      editableTranscript.value = data.clean_text;
      rawVoiceTranscript = data.raw_text;
      recordingIndicator.textContent = 'Uploaded Audio Transcribed';
      editableTranscript.focus();

    } catch (err) {
      console.error('File transcription error:', err);
      addChatMessage('system', `Error transcribing ${file.name}: ${err.message}`);
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function escapeJsString(str) {
    if (!str) return '';
    return String(str).replace(/'/g, "\\'").replace(/"/g, '\\"');
  }
});
