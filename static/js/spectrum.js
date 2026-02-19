// RTL-SDR Spectrum & Waterfall Renderer
(function() {
  const specCanvas = document.getElementById('spectrum-canvas');
  const wfCanvas = document.getElementById('waterfall-canvas');
  if (!specCanvas || !wfCanvas) return;

  const specCtx = specCanvas.getContext('2d');
  const wfCtx = wfCanvas.getContext('2d');

  function resize() {
    specCanvas.width = specCanvas.clientWidth;
    specCanvas.height = specCanvas.clientHeight || 200;
    wfCanvas.width = wfCanvas.clientWidth;
    wfCanvas.height = wfCanvas.clientHeight || 300;
  }
  resize();
  window.addEventListener('resize', resize);

  const BG = '#000000';
  const GRID = '#1a1a1a';
  const LINE = '#ff2020';
  const FILL = 'rgba(255,32,32,0.1)';

  let lastData = null;

  function drawSpectrum(data) {
    const w = specCanvas.width;
    const h = specCanvas.height;
    const len = data.length;
    if (len === 0) return;

    specCtx.fillStyle = BG;
    specCtx.fillRect(0, 0, w, h);

    // Grid lines
    specCtx.strokeStyle = GRID;
    specCtx.lineWidth = 1;
    for (let i = 0; i < 10; i++) {
      const y = (h / 10) * i;
      specCtx.beginPath();
      specCtx.moveTo(0, y);
      specCtx.lineTo(w, y);
      specCtx.stroke();
    }

    // Normalize data to 0-1 range
    let min = Infinity, max = -Infinity;
    for (let i = 0; i < len; i++) {
      if (data[i] < min) min = data[i];
      if (data[i] > max) max = data[i];
    }
    const range = max - min || 1;

    // Draw filled area
    specCtx.beginPath();
    specCtx.moveTo(0, h);
    for (let i = 0; i < len; i++) {
      const x = (i / (len - 1)) * w;
      const y = h - ((data[i] - min) / range) * (h - 20);
      if (i === 0) specCtx.lineTo(x, y);
      else specCtx.lineTo(x, y);
    }
    specCtx.lineTo(w, h);
    specCtx.closePath();
    specCtx.fillStyle = FILL;
    specCtx.fill();

    // Draw line
    specCtx.beginPath();
    for (let i = 0; i < len; i++) {
      const x = (i / (len - 1)) * w;
      const y = h - ((data[i] - min) / range) * (h - 20);
      if (i === 0) specCtx.moveTo(x, y);
      else specCtx.lineTo(x, y);
    }
    specCtx.strokeStyle = LINE;
    specCtx.lineWidth = 1.5;
    specCtx.stroke();

    // Labels
    specCtx.fillStyle = '#666';
    specCtx.font = '10px monospace';
    specCtx.fillText(max.toFixed(1) + ' dB', 4, 14);
    specCtx.fillText(min.toFixed(1) + ' dB', 4, h - 4);
  }

  function drawWaterfall(data) {
    const w = wfCanvas.width;
    const h = wfCanvas.height;
    const len = data.length;
    if (len === 0) return;

    // Shift existing content down by 1 pixel
    const imageData = wfCtx.getImageData(0, 0, w, h - 1);
    wfCtx.putImageData(imageData, 0, 1);

    // Normalize
    let min = Infinity, max = -Infinity;
    for (let i = 0; i < len; i++) {
      if (data[i] < min) min = data[i];
      if (data[i] > max) max = data[i];
    }
    const range = max - min || 1;

    // Draw new top row
    for (let i = 0; i < w; i++) {
      const idx = Math.floor((i / w) * len);
      const val = (data[idx] - min) / range;
      const r = Math.floor(val * 255);
      const g = Math.floor(val > 0.5 ? (1 - val) * 2 * 255 : val * 2 * 255);
      const b = Math.floor((1 - val) * 255);
      wfCtx.fillStyle = `rgb(${r},${g},${b})`;
      wfCtx.fillRect(i, 0, 1, 1);
    }
  }

  // SSE listener for SDR data
  const evtSource = new EventSource('/api/events/sdr');
  evtSource.addEventListener('sdr-data', function(e) {
    try {
      const data = JSON.parse(e.data);
      if (data.power && Array.isArray(data.power)) {
        lastData = data.power;
        drawSpectrum(data.power);
        drawWaterfall(data.power);
      }
    } catch (err) {}
  });

  evtSource.onerror = function() {
    // Silent reconnect
  };

  // Demo mode: draw placeholder if no data after 3s
  setTimeout(function() {
    if (!lastData) {
      specCtx.fillStyle = BG;
      specCtx.fillRect(0, 0, specCanvas.width, specCanvas.height);
      specCtx.fillStyle = '#333';
      specCtx.font = '14px monospace';
      specCtx.textAlign = 'center';
      specCtx.fillText('Start a sweep to see spectrum data', specCanvas.width / 2, specCanvas.height / 2);

      wfCtx.fillStyle = BG;
      wfCtx.fillRect(0, 0, wfCanvas.width, wfCanvas.height);
      wfCtx.fillStyle = '#333';
      wfCtx.font = '14px monospace';
      wfCtx.textAlign = 'center';
      wfCtx.fillText('Waterfall display', wfCanvas.width / 2, wfCanvas.height / 2);
    }
  }, 3000);
})();
