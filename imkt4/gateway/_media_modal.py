"""Snippet compartilhado: modal de preview pra imagens/vídeos/áudios.

Incluir no final do HTML de cada UI (antes do </body>). Adiciona:
  - CSS do overlay + fechar
  - Função global openMediaModal(url)
  - Listener delegado em document.body — detecta clicks em
    <img>, <video>, <audio>, ou <a href="..."> com url de mídia
    e abre no modal em vez de abrir nova aba.

Fecha com ESC ou click fora.
"""

MEDIA_MODAL_HTML = r"""
<style>
#media-modal {
  display: none;
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(0,0,0,0.92);
  align-items: center; justify-content: center;
  padding: 20px;
  cursor: zoom-out;
}
#media-modal.open { display: flex; }
#media-modal .inner {
  max-width: 95vw; max-height: 95vh;
  display: flex; flex-direction: column;
  align-items: center; gap: 12px;
  cursor: default;
}
#media-modal img,
#media-modal video {
  max-width: 95vw;
  max-height: 85vh;
  border-radius: 8px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.6);
  background: #0d1117;
}
#media-modal audio {
  width: min(600px, 90vw);
}
#media-modal .bar {
  display: flex; gap: 12px; align-items: center;
  color: #e6edf3; font-size: 12px;
  background: rgba(13,17,23,0.9); padding: 8px 14px;
  border-radius: 8px; border: 1px solid #30363d;
}
#media-modal .bar a {
  color: #1f6feb; text-decoration: none; font-size: 11px;
}
#media-modal .bar a:hover { text-decoration: underline; }
#media-modal .bar button {
  background: transparent; border: 1px solid #30363d;
  color: #e6edf3; padding: 4px 10px; border-radius: 4px;
  font-size: 11px; cursor: pointer;
}
#media-modal .bar button:hover { background: #21262d; }

#media-modal .media-nav {
  position: absolute;
  top: 50%; transform: translateY(-50%);
  background: rgba(13,17,23,0.85); color: #e6edf3;
  border: 1px solid #30363d; border-radius: 50%;
  width: 56px; height: 56px;
  font-size: 36px; line-height: 1; font-weight: 300;
  cursor: pointer; user-select: none;
  display: none; align-items: center; justify-content: center;
  transition: background 0.1s;
}
#media-modal .media-nav:hover { background: rgba(31,111,235,0.9); }
#media-modal.open.multi .media-nav { display: flex; }
#media-modal .media-nav.prev { left: 24px; }
#media-modal .media-nav.next { right: 24px; }
#media-modal .media-nav:disabled { opacity: 0.3; cursor: default; background: rgba(13,17,23,0.85) !important; }

/* Backlog #22 — botão X universal de fechar modal no canto */
#media-modal .close-x {
  position: absolute;
  top: 20px; right: 24px;
  background: rgba(13,17,23,0.85); color: #e6edf3;
  border: 1px solid rgba(255,255,255,0.25);
  border-radius: 50%;
  width: 44px; height: 44px;
  font-size: 22px; line-height: 1; font-weight: 300;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background 0.15s, border-color 0.15s;
  z-index: 10001;
}
#media-modal .close-x:hover {
  background: rgba(220, 60, 60, 0.9);
  border-color: white;
}
</style>

<div id="media-modal" onclick="closeMediaModal(event)">
  <button class="close-x" onclick="event.stopPropagation(); closeMediaModal();" title="Fechar (ESC)">×</button>
  <button class="media-nav prev" id="media-prev-btn" onclick="event.stopPropagation(); mediaNav(-1);">‹</button>
  <button class="media-nav next" id="media-next-btn" onclick="event.stopPropagation(); mediaNav(1);">›</button>
  <div class="inner" onclick="event.stopPropagation()">
    <div id="media-modal-body"></div>
    <div class="bar">
      <span id="media-modal-counter" style="color:#7d8590;font-size:11px;"></span>
      <span id="media-modal-url" style="font-family:monospace;color:#7d8590;"></span>
      <a id="media-modal-download" download>baixar</a>
      <a id="media-modal-open-tab" target="_blank" rel="noopener">abrir em nova aba</a>
      <button onclick="closeMediaModal()">fechar (esc)</button>
    </div>
  </div>
</div>

<script>
(function(){
  const IMG_RE = /\.(png|jpe?g|webp|gif|avif)(\?|$)/i;
  const VID_RE = /\.(mp4|webm|mov|m4v)(\?|$)/i;
  const AUD_RE = /\.(mp3|wav|m4a|ogg|flac)(\?|$)/i;

  function mediaKind(url) {
    if (!url) return null;
    if (IMG_RE.test(url)) return 'img';
    if (VID_RE.test(url)) return 'video';
    if (AUD_RE.test(url)) return 'audio';
    return null;
  }

  // Gallery state — lista de todas as mídias visíveis na página
  let _mediaList = [];
  let _mediaIdx = -1;

  function collectMediaUrls() {
    const seen = new Set();
    const urls = [];
    // <img>
    document.querySelectorAll('img').forEach(img => {
      if (img.closest('#media-modal')) return;
      if (img.closest('.no-modal')) return;
      if (img.src && !seen.has(img.src)) { seen.add(img.src); urls.push(img.src); }
    });
    // <a href="..."> de mídia
    document.querySelectorAll('a').forEach(a => {
      if (a.closest('#media-modal')) return;
      if (a.href && mediaKind(a.href) && !seen.has(a.href)) {
        seen.add(a.href); urls.push(a.href);
      }
    });
    return urls;
  }

  function renderCurrent() {
    const modal = document.getElementById('media-modal');
    const body = document.getElementById('media-modal-body');
    const url = _mediaList[_mediaIdx];
    if (!url) return;
    body.innerHTML = '';
    const kind = mediaKind(url);
    let el;
    if (kind === 'video') {
      el = document.createElement('video');
      el.src = url; el.controls = true; el.autoplay = true;
    } else if (kind === 'audio') {
      el = document.createElement('audio');
      el.src = url; el.controls = true; el.autoplay = true;
    } else {
      el = document.createElement('img');
      el.src = url;
    }
    body.appendChild(el);

    document.getElementById('media-modal-url').textContent =
      url.length > 70 ? url.slice(0,35) + '…' + url.slice(-30) : url;
    document.getElementById('media-modal-download').href = url;
    document.getElementById('media-modal-open-tab').href = url;

    // Counter e botões nav
    const multi = _mediaList.length > 1;
    modal.classList.toggle('multi', multi);
    document.getElementById('media-modal-counter').textContent =
      multi ? `${_mediaIdx + 1} / ${_mediaList.length}` : '';
    document.getElementById('media-prev-btn').disabled = _mediaIdx === 0;
    document.getElementById('media-next-btn').disabled = _mediaIdx === _mediaList.length - 1;
  }

  window.openMediaModal = function(url) {
    if (!url) return;
    _mediaList = collectMediaUrls();
    _mediaIdx = _mediaList.indexOf(url);
    if (_mediaIdx === -1) {
      _mediaList = [url]; _mediaIdx = 0;
    }
    document.getElementById('media-modal').classList.add('open');
    renderCurrent();
  };

  window.mediaNav = function(delta) {
    const next = _mediaIdx + delta;
    if (next < 0 || next >= _mediaList.length) return;
    _mediaIdx = next;
    renderCurrent();
  };

  window.closeMediaModal = function(ev) {
    if (ev && ev.target && ev.target.closest && ev.target.closest('.inner')) return;
    const modal = document.getElementById('media-modal');
    const body = document.getElementById('media-modal-body');
    modal.classList.remove('open');
    body.innerHTML = '';  // para vídeo/áudio
  };

  document.addEventListener('keydown', e => {
    const modal = document.getElementById('media-modal');
    if (!modal || !modal.classList.contains('open')) return;
    if (e.key === 'Escape') window.closeMediaModal();
    else if (e.key === 'ArrowLeft') window.mediaNav(-1);
    else if (e.key === 'ArrowRight') window.mediaNav(1);
  });

  // Delegated click: detecta img, video, audio OU anchor com url de mídia
  document.addEventListener('click', function(e) {
    const t = e.target;
    if (!t) return;
    if (t.closest('#media-modal')) return;
    // ignora elementos de controle de <video> (clicks no play)
    if (t.tagName === 'VIDEO' || t.tagName === 'AUDIO') return;

    let url = null;
    if (t.tagName === 'IMG' && t.src && !t.closest('.no-modal')) {
      url = t.src;
    }
    // Anchor com href de mídia — intercepta
    const a = t.closest && t.closest('a');
    if (a && a.href && mediaKind(a.href)) {
      url = a.href;
    }
    if (url) {
      e.preventDefault();
      window.openMediaModal(url);
    }
  });
})();
</script>
"""
