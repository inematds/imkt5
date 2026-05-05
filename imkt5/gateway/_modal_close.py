"""Snippet universal de comportamento de modal (Backlog #22).

Aplica a TODOS os modais da app (não só mídia):
  - Botão X automático no canto superior direito
  - ESC fecha o modal
  - Click fora da caixa de conteúdo fecha

Convenção: qualquer elemento com atributo `data-modal` OU com
`id` terminando em `-modal` OU `role="dialog"` vira um "modal
gerenciado" — ganha X injetado e listeners de ESC/click-fora.

A UI não precisa mudar marcação — incluir o HTML/script uma vez
antes do </body>.
"""

UNIVERSAL_MODAL_HTML = r"""
<style>
/* Backlog #22 — botão X injetado em qualquer modal */
.imkt5-modal-x {
  position: absolute;
  top: 12px; right: 14px;
  background: rgba(13,17,23,0.85); color: #e6edf3;
  border: 1px solid rgba(255,255,255,0.25);
  border-radius: 50%;
  width: 32px; height: 32px;
  font-size: 18px; line-height: 1; font-weight: 300;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background 0.15s, border-color 0.15s;
  z-index: 10001;
}
.imkt5-modal-x:hover {
  background: rgba(220, 60, 60, 0.9);
  border-color: white;
}

/* Classe .imkt5-managed-modal (adicionada automaticamente):
   garante relative no card interno pra X posicionar ok */
.imkt5-managed-modal > div,
.imkt5-managed-modal > .inner,
.imkt5-managed-modal > section,
.imkt5-managed-modal > form {
  position: relative;
}
</style>

<script>
(function(){
  // Seleciona elementos que são "modais gerenciados"
  function findManagedModals() {
    const els = new Set();
    document.querySelectorAll('[data-modal], [role="dialog"]').forEach(e => els.add(e));
    document.querySelectorAll('[id$="-modal"]').forEach(e => {
      // pula #media-modal (já tem seu próprio handler)
      if (e.id === 'media-modal') return;
      els.add(e);
    });
    return els;
  }

  function isVisible(el) {
    if (!el) return false;
    const s = window.getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden';
  }

  function findCloseFn(el) {
    // 1) atributo data-modal-close pode apontar função
    const fn = el.getAttribute('data-modal-close');
    if (fn && typeof window[fn] === 'function') return () => window[fn]();
    // 2) convenção: {id}.replace('-modal','Dialog') ou 'close'+id
    const id = el.id || '';
    // close<Foo>Dialog, closeFooDialog
    const candidates = [];
    if (id.endsWith('-modal')) {
      const base = id.slice(0, -6);  // remove "-modal"
      const camel = base.replace(/-([a-z])/g, (_,c) => c.toUpperCase());
      const pascal = camel.charAt(0).toUpperCase() + camel.slice(1);
      candidates.push('close' + pascal + 'Dialog');
      candidates.push('close' + pascal + 'Modal');
      candidates.push('close' + pascal);
    }
    for (const name of candidates) {
      if (typeof window[name] === 'function') return () => window[name]();
    }
    // 3) fallback: só esconde display:none
    return () => { el.style.display = 'none'; };
  }

  function injectCloseX(el) {
    if (el.querySelector(':scope > .imkt5-modal-x')) return;  // já tem
    const btn = document.createElement('button');
    btn.className = 'imkt5-modal-x';
    btn.setAttribute('title', 'Fechar (ESC)');
    btn.textContent = '×';
    btn.onclick = function(ev) {
      ev.stopPropagation();
      findCloseFn(el)();
    };
    // Se não tem position absolute/fixed, força relative no container
    const s = window.getComputedStyle(el);
    if (s.position === 'static') el.style.position = 'relative';
    el.classList.add('imkt5-managed-modal');
    el.appendChild(btn);
  }

  function ensureOverlayClickClose(el) {
    if (el.dataset.imkt5OverlayBound === '1') return;
    el.dataset.imkt5OverlayBound = '1';
    // opt-out: data-modal-no-dismiss="1" desabilita fechar por click-fora
    if (el.dataset.modalNoDismiss === '1') return;
    el.addEventListener('click', function(ev) {
      // Se clicou no próprio overlay (não dentro de um filho), fecha
      if (ev.target === el) {
        findCloseFn(el)();
      }
    });
  }

  // Observer — re-aplica quando novos modais forem adicionados ao DOM
  function apply() {
    const modals = findManagedModals();
    modals.forEach(el => {
      injectCloseX(el);
      ensureOverlayClickClose(el);
    });
  }

  // ESC global — fecha o modal visível mais "superior" (maior z-index)
  // Ignora modais com data-modal-no-dismiss="1" (ex.: form de nova execução)
  document.addEventListener('keydown', function(ev) {
    if (ev.key !== 'Escape') return;
    const modals = [...findManagedModals()]
      .filter(isVisible)
      .filter(el => el.dataset.modalNoDismiss !== '1');
    if (!modals.length) return;
    // pega o de maior z-index
    modals.sort((a, b) => {
      const za = parseInt(window.getComputedStyle(a).zIndex) || 0;
      const zb = parseInt(window.getComputedStyle(b).zIndex) || 0;
      return zb - za;
    });
    findCloseFn(modals[0])();
  });

  // Init + observe
  if (document.readyState !== 'loading') apply();
  else document.addEventListener('DOMContentLoaded', apply);

  const mo = new MutationObserver(() => apply());
  mo.observe(document.body || document.documentElement,
             { childList: true, subtree: true });
})();
</script>
"""
