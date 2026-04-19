/* ── canvas particle background ─────────────────────────────────────────── */
(function () {
  const canvas = document.getElementById('bg-canvas');
  const ctx    = canvas.getContext('2d');
  let W, H, particles;

  function resize() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  function initParticles() {
    particles = Array.from({ length: 60 }, () => ({
      x: Math.random() * W,
      y: Math.random() * H,
      r: Math.random() * 1.5 + 0.5,
      vx: (Math.random() - 0.5) * 0.3,
      vy: (Math.random() - 0.5) * 0.3,
      alpha: Math.random() * 0.5 + 0.1,
    }));
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    particles.forEach(p => {
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(168, 85, 247, ${p.alpha})`;
      ctx.fill();

      p.x += p.vx;
      p.y += p.vy;
      if (p.x < 0) p.x = W;
      if (p.x > W) p.x = 0;
      if (p.y < 0) p.y = H;
      if (p.y > H) p.y = 0;
    });

    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 120) {
          ctx.beginPath();
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.strokeStyle = `rgba(124, 58, 255, ${0.08 * (1 - dist / 120)})`;
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }
      }
    }

    requestAnimationFrame(draw);
  }

  window.addEventListener('resize', () => { resize(); initParticles(); });
  resize();
  initParticles();
  draw();
})();


/* ── health check ────────────────────────────────────────────────────────── */
async function checkHealth() {
  try {
    const r = await fetch('/health');
    const d = await r.json();
    dot('dot-groq',   d.groq);
    dot('dot-gemini', d.gemini);
    dot('dot-or',     d.openrouter);
  } catch { /* silent */ }
}

function dot(id, on) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.toggle('on',  !!on);
  el.classList.toggle('off', !on);
}

checkHealth();


/* ── tabs ────────────────────────────────────────────────────────────────── */
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => {
      p.classList.remove('active');
      p.classList.add('hidden');
    });
    tab.classList.add('active');
    const panel = document.getElementById('panel-' + tab.dataset.tab);
    panel.classList.remove('hidden');
    panel.classList.add('active');
  });
});


/* ── char counter ────────────────────────────────────────────────────────── */
const msgArea = document.getElementById('enc-message');
const charCnt = document.getElementById('char-count');
msgArea.addEventListener('input', () => {
  charCnt.textContent = `${msgArea.value.length} / ~2000 chars`;
});


/* ── region pickers ──────────────────────────────────────────────────────── */
function setupRegionPicker(pickerId, hiddenId) {
  const picker = document.getElementById(pickerId);
  const hidden = document.getElementById(hiddenId);
  if (!picker || !hidden) return;

  picker.querySelectorAll('.region-cell').forEach(btn => {
    btn.addEventListener('click', () => {
      picker.querySelectorAll('.region-cell').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      hidden.value = btn.dataset.region;
    });
  });
}

setupRegionPicker('region-picker',     'enc-region');
setupRegionPicker('dec-region-picker', 'dec-region');


/* ── terminal bridge helper ──────────────────────────────────────────────── */
async function sendToTerminal(b64data, filename) {
  const blob = b64ToBlob(b64data, 'image/png');
  const form = new FormData();
  form.append('file', new File([blob], filename, { type: 'image/png' }));

  try {
    const resp = await fetch('/terminal/upload', { method: 'POST', body: form });
    const data = await resp.json();
    // hand off to terminal.js
    if (window.terminalSetSession) {
      window.terminalSetSession(data.session_id, data.filename);
    }
    // switch to terminal tab
    document.querySelector('[data-tab="terminal"]').click();
  } catch {
    alert('Failed to send image to terminal.');
  }
}


/* ── ENCODE ──────────────────────────────────────────────────────────────── */
const btnEncode    = document.getElementById('btn-encode');
const encodeLoader = document.getElementById('encode-loader');
const encodeResult = document.getElementById('encode-result');
const encodeError  = document.getElementById('encode-error');
const resultImg    = document.getElementById('result-img');
const metaPrompt   = document.getElementById('meta-prompt');
const metaSize     = document.getElementById('meta-size');
const metaRegion   = document.getElementById('meta-region');
const btnDownload  = document.getElementById('btn-download');

function setStep(id, state) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('active', 'done');
  if (state) el.classList.add(state);
}

let downloadUrl    = null;
let lastEncodeB64  = null;

btnEncode.addEventListener('click', async () => {
  const message = msgArea.value.trim();
  const style   = document.getElementById('enc-style').value.trim();
  const extra   = document.getElementById('enc-extra').value.trim();
  const region  = document.getElementById('enc-region').value;

  if (!message) return showError(encodeError, 'Please enter a secret message.');
  if (!style)   return showError(encodeError, 'Please describe an art style.');

  encodeError.classList.add('hidden');
  encodeResult.classList.add('hidden');
  encodeLoader.classList.remove('hidden');
  btnEncode.disabled = true;

  setStep('step-1', 'active');
  setStep('step-2', null);
  setStep('step-3', null);

  const stepTimer1 = setTimeout(() => {
    setStep('step-1', 'done');
    setStep('step-2', 'active');
  }, 1200);

  const stepTimer2 = setTimeout(() => {
    setStep('step-2', 'done');
    setStep('step-3', 'active');
  }, 4000);

  try {
    const resp = await fetch('/encode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, style, extra_prompt: extra, region }),
    });

    clearTimeout(stepTimer1);
    clearTimeout(stepTimer2);

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || 'Server error');
    }

    const data = await resp.json();
    lastEncodeB64 = data.image_b64;

    setStep('step-1', 'done');
    setStep('step-2', 'done');
    setStep('step-3', 'done');

    setTimeout(() => {
      encodeLoader.classList.add('hidden');

      const imgSrc = `data:image/png;base64,${data.image_b64}`;
      resultImg.src = imgSrc;
      metaPrompt.textContent = data.enhanced_prompt;
      metaSize.textContent   = `${data.image_size_kb} KB`;
      metaRegion.textContent = data.region || region;

      if (downloadUrl) URL.revokeObjectURL(downloadUrl);
      const blob = b64ToBlob(data.image_b64, 'image/png');
      downloadUrl = URL.createObjectURL(blob);
      btnDownload.onclick = () => {
        const a = document.createElement('a');
        a.href     = downloadUrl;
        a.download = `steg-art-${Date.now()}.png`;
        a.click();
      };

      encodeResult.classList.remove('hidden');
    }, 500);

  } catch (err) {
    clearTimeout(stepTimer1);
    clearTimeout(stepTimer2);
    encodeLoader.classList.add('hidden');
    showError(encodeError, err.message);
  } finally {
    btnEncode.disabled = false;
  }
});

// "Analyze in Terminal" from encode result
document.getElementById('btn-encode-to-terminal').addEventListener('click', () => {
  if (lastEncodeB64) sendToTerminal(lastEncodeB64, `steg-art-${Date.now()}.png`);
});


/* ── DECODE ──────────────────────────────────────────────────────────────── */
const dropZone      = document.getElementById('drop-zone');
const decodeFile    = document.getElementById('decode-file');
const decodePreview = document.getElementById('decode-preview');
const decodeImg     = document.getElementById('decode-img');
const btnDecode     = document.getElementById('btn-decode');
const decodeBtnRow  = document.getElementById('decode-btn-row');
const decRegionWrap = document.getElementById('dec-region-wrap');
const decodeLoader  = document.getElementById('decode-loader');
const decodeResult  = document.getElementById('decode-result');
const decodeError   = document.getElementById('decode-error');
const revealedMsg   = document.getElementById('revealed-msg');
const btnCopy       = document.getElementById('btn-copy');

let selectedFile = null;

function loadPreview(file) {
  selectedFile = file;
  const reader = new FileReader();
  reader.onload = e => {
    decodeImg.src = e.target.result;
    decodePreview.classList.remove('hidden');
    decodeBtnRow.classList.remove('hidden');
    decRegionWrap.classList.remove('hidden');
    decodeResult.classList.add('hidden');
    decodeError.classList.add('hidden');
  };
  reader.readAsDataURL(file);
}

dropZone.addEventListener('click', () => decodeFile.click());
decodeFile.addEventListener('change', () => {
  if (decodeFile.files[0]) loadPreview(decodeFile.files[0]);
});

dropZone.addEventListener('dragover', e => {
  e.preventDefault();
  dropZone.classList.add('drag-over');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) loadPreview(e.dataTransfer.files[0]);
});

btnDecode.addEventListener('click', async () => {
  if (!selectedFile) return;

  decodeError.classList.add('hidden');
  decodeResult.classList.add('hidden');
  decodeLoader.classList.remove('hidden');
  btnDecode.disabled = true;

  setStep('dec-step-1', 'active');
  setStep('dec-step-2', null);

  const t = setTimeout(() => {
    setStep('dec-step-1', 'done');
    setStep('dec-step-2', 'active');
  }, 600);

  const form = new FormData();
  form.append('file', selectedFile);
  form.append('region', document.getElementById('dec-region').value);

  try {
    const resp = await fetch('/decode', { method: 'POST', body: form });
    clearTimeout(t);

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || 'Failed to decode');
    }

    const data = await resp.json();
    setStep('dec-step-1', 'done');
    setStep('dec-step-2', 'done');

    setTimeout(() => {
      decodeLoader.classList.add('hidden');
      revealedMsg.textContent = data.message;

      const m    = data.meta;
      const grid = document.getElementById('steg-meta-grid');
      grid.innerHTML = '';
      const rows = [
        ['Method',      m.method,                                                   false],
        ['Region',      m.region,                                                   false],
        ['Bit planes',  m.bit_planes,                                               true],
        ['Channels',    m.channels.join(', '),                                      false],
        ['Image size',  m.image_size,                                               false],
        ['Pixel range', m.pixel_range,                                              false],
        ['Row range',   m.row_range,                                                false],
        ['Pixels used', `${m.pixels_used.toLocaleString()} / ${m.total_pixels.toLocaleString()} (${m.pct_used}%)`, true],
        ['Bits used',   `${m.bits_used} bits = ${m.bytes_used} bytes`,              true],
        ['Capacity',    `~${m.capacity_chars.toLocaleString()} chars max`,          false],
      ];
      rows.forEach(([k, v, full]) => {
        const el = document.createElement('div');
        el.className = 'steg-meta-item' + (full ? ' full' : '');
        el.innerHTML = `<span class="k">${k}</span><span class="v">${v}</span>`;
        grid.appendChild(el);
      });

      decodeResult.classList.remove('hidden');
    }, 300);

  } catch (err) {
    clearTimeout(t);
    decodeLoader.classList.add('hidden');
    showError(decodeError, err.message);
  } finally {
    btnDecode.disabled = false;
  }
});

// "Analyze in Terminal" from decode tab
document.getElementById('btn-decode-to-terminal').addEventListener('click', () => {
  if (!selectedFile) return;
  const reader = new FileReader();
  reader.onload = e => {
    const b64 = e.target.result.split(',')[1];
    sendToTerminal(b64, selectedFile.name);
  };
  reader.readAsDataURL(selectedFile);
});

btnCopy.addEventListener('click', () => {
  navigator.clipboard.writeText(revealedMsg.textContent).then(() => {
    btnCopy.textContent = 'Copied!';
    setTimeout(() => btnCopy.textContent = 'Copy', 1500);
  });
});


/* ── utils ───────────────────────────────────────────────────────────────── */
function showError(el, msg) {
  el.textContent = '⚠ ' + msg;
  el.classList.remove('hidden');
}

function b64ToBlob(b64, mime) {
  const bytes = atob(b64);
  const arr   = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return new Blob([arr], { type: mime });
}
