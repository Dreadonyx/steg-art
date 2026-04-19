/* terminal.js — steg-art terminal emulator
   Adapted from Dreadonyx/Linux-command-simulator
   Steg-only commands: strings binwalk steghide stegseek exiftool xxd file zsteg base64 md5sum sha256sum
*/

(function () {
  const termOutput = document.getElementById('term-output');
  const termDrop   = document.getElementById('term-drop');
  const termFile   = document.getElementById('term-file');
  const imgLabel   = document.getElementById('term-img-label');

  let sessionId  = null;
  let imageName  = null;
  let inputSpan  = null;
  let cmdHistory = [];
  let histIdx    = -1;

  function getPrompt() {
    return imageName ? `steg@art [${imageName}]$ ` : 'steg@art [no image]$ ';
  }

  // ── output helpers ────────────────────────────────────────────────────────
  function print(text, cls) {
    const div = document.createElement('div');
    div.className = 'term-out' + (cls ? ' ' + cls : '');
    div.textContent = text;
    termOutput.appendChild(div);
    scrollBottom();
  }

  function scrollBottom() {
    termOutput.scrollTop = termOutput.scrollHeight;
  }

  // ── prompt line ───────────────────────────────────────────────────────────
  function createPromptLine() {
    const line = document.createElement('div');
    line.className = 'term-line';

    const pr = document.createElement('span');
    pr.className = 'term-prompt';
    pr.textContent = getPrompt();

    inputSpan = document.createElement('span');
    inputSpan.className = 'term-input';
    inputSpan.contentEditable = true;
    inputSpan.spellcheck = false;
    inputSpan.innerHTML = '\u200B';   // zero-width space keeps cursor from dropping

    inputSpan.addEventListener('input', function () {
      if (!this.textContent || this.innerHTML === '<br>') {
        this.innerHTML = '\u200B';
        placeEnd(this);
      }
    });

    line.appendChild(pr);
    line.appendChild(inputSpan);
    termOutput.appendChild(line);
    histIdx = cmdHistory.length;
    placeEnd(inputSpan);
    scrollBottom();
  }

  function placeEnd(el) {
    el.focus();
    const r = document.createRange();
    r.selectNodeContents(el);
    r.collapse(false);
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
  }

  // ── image upload ──────────────────────────────────────────────────────────
  function handleUpload(file) {
    if (!file.type.startsWith('image/')) {
      print('Error: not an image file.', 'term-err');
      return;
    }
    const form = new FormData();
    form.append('file', file);

    imgLabel.textContent = 'Uploading…';

    fetch('/terminal/upload', { method: 'POST', body: form })
      .then(r => r.json())
      .then(d => {
        sessionId = d.session_id;
        imageName = d.filename;
        imgLabel.textContent = `◈ ${imageName} — ready`;
        imgLabel.classList.add('loaded');
        termDrop.classList.add('loaded');

        // refresh prompt if one exists
        const lastPrompt = termOutput.querySelector('.term-line:last-child .term-prompt');
        if (lastPrompt) lastPrompt.textContent = getPrompt();

        print(`Loaded: ${imageName}`, 'term-info');
        print('Type  help  for available commands.', 'term-dim');
        scrollBottom();
      })
      .catch(() => {
        imgLabel.textContent = 'Drop or click to load image for analysis';
        print('Upload failed.', 'term-err');
      });
  }

  termDrop.addEventListener('click', () => termFile.click());
  termFile.addEventListener('change', () => termFile.files[0] && handleUpload(termFile.files[0]));

  termDrop.addEventListener('dragover',  e => { e.preventDefault(); termDrop.classList.add('drag-over'); });
  termDrop.addEventListener('dragleave', () => termDrop.classList.remove('drag-over'));
  termDrop.addEventListener('drop', e => {
    e.preventDefault();
    termDrop.classList.remove('drag-over');
    e.dataTransfer.files[0] && handleUpload(e.dataTransfer.files[0]);
  });

  // ── run command via backend ───────────────────────────────────────────────
  function runCommand(cmd) {
    if (!sessionId) {
      print('No image loaded. Drop an image in the strip above first.', 'term-err');
      createPromptLine();
      return;
    }

    fetch('/terminal/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, command: cmd }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.clear) {
          termOutput.innerHTML = '';
          createPromptLine();
          return;
        }
        if (d.output) {
          const isErr = /not found|Error:|error:|failed|command not found/.test(d.output);
          print(d.output, isErr ? 'term-err' : '');
        }
        createPromptLine();
        scrollBottom();
      })
      .catch(() => {
        print('Request failed.', 'term-err');
        createPromptLine();
      });
  }

  // ── keyboard handler ──────────────────────────────────────────────────────
  document.addEventListener('keydown', function (e) {
    // only active when terminal tab is visible
    const panel = document.getElementById('panel-terminal');
    if (!panel || !panel.classList.contains('active')) return;
    if (!inputSpan) return;

    if (e.key === 'Enter') {
      e.preventDefault();
      const cmd = inputSpan.textContent.replace(/\u200B/g, '').trim();
      inputSpan.contentEditable = false;
      if (!cmd) { createPromptLine(); return; }
      if (!cmdHistory.length || cmdHistory[cmdHistory.length - 1] !== cmd) {
        cmdHistory.push(cmd);
      }
      runCommand(cmd);

    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (histIdx > 0) {
        histIdx--;
        inputSpan.textContent = cmdHistory[histIdx];
        placeEnd(inputSpan);
      }

    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (histIdx < cmdHistory.length - 1) {
        histIdx++;
        inputSpan.textContent = cmdHistory[histIdx];
        placeEnd(inputSpan);
      } else {
        histIdx = cmdHistory.length;
        inputSpan.textContent = '';
      }
    }
  });

  // click anywhere in term body to refocus input
  document.getElementById('term-output').addEventListener('click', function () {
    if (inputSpan) placeEnd(inputSpan);
  });

  // ── init ──────────────────────────────────────────────────────────────────
  print('steg-art terminal  —  drop an image above to get started', 'term-dim');
  createPromptLine();
})();
