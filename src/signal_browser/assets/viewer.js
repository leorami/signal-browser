function initials(name){
  return (name||'').split(/\s+/).slice(0,2).map(s => (s[0]||'').toUpperCase()).join('') || '?';
}

function escapeRe(s){
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function appendHighlighted(parent, text, q){
  const raw = String(text || '');
  const needle = (q || '').trim();
  if (!raw){ return; }
  if (needle.length < 2){
    parent.appendChild(linkify(raw));
    return;
  }
  const re = new RegExp(escapeRe(needle), 'gi');
  let last = 0;
  raw.replace(re, (match, idx) => {
    if (idx > last) parent.appendChild(linkify(raw.slice(last, idx)));
    const mark = document.createElement('mark');
    mark.className = 'hit';
    mark.textContent = match;
    parent.appendChild(mark);
    last = idx + match.length;
    return match;
  });
  if (last < raw.length) parent.appendChild(linkify(raw.slice(last)));
}

function linkify(text){
  const frag = document.createDocumentFragment();
  if(!text){ return frag; }
  const urlRe = /(?:https?:\/\/|www\.)[\w\-\.\?\,\/%#&=:+~@!$'()*]+/gi;
  let last = 0;
  String(text).replace(urlRe, (match, idx) => {
    if(idx > last){ frag.appendChild(document.createTextNode(text.slice(last, idx))); }
    const href = match.startsWith('www.') ? ('https://' + match) : match;
    const a = document.createElement('a');
    a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer';
    a.textContent = match;
    frag.appendChild(a);
    last = idx + match.length;
    return match;
  });
  if(last < String(text).length){ frag.appendChild(document.createTextNode(text.slice(last))); }
  return frag;
}

function mediaUrl(path, resolve){
  if(!path) return '';
  if(resolve) return resolve(path);
  return path;
}

function liAvatar(t, resolve){
  if(t.avatar && !t.avatarEncrypted){
    const img = document.createElement('img');
    img.className = 'avatar';
    img.alt = '';
    img.src = mediaUrl(t.avatar, resolve);
    img.onerror = () => { img.replaceWith(dotAvatar(t.thread)); };
    return img;
  }
  return dotAvatar(t.thread);
}

function dotAvatar(name){
  const dot = document.createElement('div');
  dot.className = 'dot';
  dot.textContent = initials(name);
  return dot;
}

function shortDate(ms){
  if(!ms) return '';
  const d = new Date(ms);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if(sameDay) return d.toLocaleTimeString([], {hour:'numeric', minute:'2-digit'});
  return d.toLocaleDateString([], {month:'short', day:'numeric'});
}

function dayKey(ms){ return new Date(ms).toLocaleDateString(); }
function timeText(ms){ return new Date(ms).toLocaleTimeString([], {hour:'numeric', minute:'2-digit'}); }

function fileLabel(a){
  return (a.name || a.path || 'file').split('/').pop();
}

function snippet(text, q, max){
  const raw = String(text || '').replace(/\s+/g, ' ').trim();
  if (!raw) return '';
  const needle = (q || '').toLowerCase();
  const i = raw.toLowerCase().indexOf(needle);
  const width = max || 88;
  if (i < 0) return raw.slice(0, width);
  const start = Math.max(0, i - 24);
  const end = Math.min(raw.length, i + needle.length + 40);
  return (start ? '…' : '') + raw.slice(start, end) + (end < raw.length ? '…' : '');
}

function messageMatches(m, q){
  const parts = [m.body || '', m.caption || ''];
  if (m.quote && m.quote.body) parts.push(m.quote.body);
  return parts.join(' ').toLowerCase().includes(q);
}

function localMessageHits(threads, q){
  const hits = [];
  (threads || []).forEach(t => {
    (t.messages || []).forEach(m => {
      if (!messageMatches(m, q)) return;
      hits.push({
        threadId: t.id,
        thread: t.thread,
        body: m.body || m.caption || '',
        ts: m.ts || 0
      });
    });
  });
  return hits;
}

function renderAttachment(a, resolve){
  const wrap = document.createElement('div');
  if(!a.path) return wrap;
  const src = mediaUrl(a.path, resolve);
  const mime = a.mime || a.contentType || '';
  const kind = (a.attachmentType || '').toLowerCase();
  if(kind === 'sticker' || (mime.startsWith('image/') && kind === 'sticker')){
    const img = document.createElement('img');
    img.src = mediaUrl(a.thumb || a.path, resolve);
    img.alt = 'Sticker';
    img.style.maxWidth = '140px';
    wrap.appendChild(img);
    return wrap;
  }
  if(mime.startsWith('image/')){
    const img = document.createElement('img');
    img.src = mediaUrl(a.thumb || a.path, resolve);
    img.alt = fileLabel(a);
    img.onclick = () => openLightbox(src, 'img');
    wrap.appendChild(img);
    return wrap;
  }
  if(mime.startsWith('video/')){
    const video = document.createElement('video');
    video.controls = true;
    video.src = src;
    if(a.poster) video.poster = mediaUrl(a.poster, resolve);
    wrap.appendChild(video);
    return wrap;
  }
  if(mime.startsWith('audio/')){
    const audio = document.createElement('audio');
    audio.controls = true;
    audio.src = src;
    wrap.appendChild(audio);
    return wrap;
  }
  const card = document.createElement('a');
  card.className = 'file-card';
  card.href = src;
  card.target = '_blank';
  card.rel = 'noopener';
  card.textContent = (a.icon === 'pdf' ? 'PDF · ' : '') + fileLabel(a);
  if(a.likelyEncrypted) card.title = 'This looks encrypted or unreadable';
  wrap.appendChild(card);
  return wrap;
}

function openLightbox(src, kind){
  const box = document.getElementById('lightbox');
  if(!box){
    window.open(src, '_blank');
    return;
  }
  box.innerHTML = '';
  box.classList.add('active');
  const el = document.createElement(kind === 'video' ? 'video' : 'img');
  el.src = src;
  if(kind === 'video') el.controls = true;
  box.appendChild(el);
  box.onclick = () => box.classList.remove('active');
}

function renderThread(t, msgsEl, titleEl, countEl, resolve, focusTs, query){
  titleEl.textContent = t.thread;
  countEl.textContent = (t.messages||[]).length + ' messages';
  const container = msgsEl.querySelector('.container') || msgsEl;
  container.innerHTML = '';
  const q = (query || '').trim();
  let lastDay = null;
  (t.messages||[]).forEach(m => {
    const dk = dayKey(m.ts);
    if (dk !== lastDay){
      lastDay = dk;
      const day = document.createElement('div'); day.className = 'day';
      const chip = document.createElement('span'); chip.textContent = dk;
      day.appendChild(chip); container.appendChild(day);
    }
    if (m.kind === 'call'){
      const row = document.createElement('div');
      row.className = 'call' + (m.missed ? ' missed' : '');
      row.dataset.ts = String(m.ts || '');
      const pill = document.createElement('div'); pill.className = 'pill';
      const icon = document.createElement('span'); icon.className = 'icon';
      icon.textContent = m.video ? '📹' : '📞';
      const txt = document.createElement('span');
      appendHighlighted(txt, m.body, q);
      const sep = document.createElement('span'); sep.textContent = ' • ';
      const ts = document.createElement('span'); ts.className = 'clock'; ts.textContent = timeText(m.ts);
      pill.append(icon, txt, sep, ts);
      row.appendChild(pill);
      container.appendChild(row);
      return;
    }
    const wrap = document.createElement('div');
    wrap.className = 'msg' + (m.out ? ' me' : '');
    wrap.dataset.ts = String(m.ts || '');
    if (m.group && !m.out){
      const s = document.createElement('div'); s.className = 'sender'; s.textContent = m.sender || '';
      wrap.appendChild(s);
    }
    if (m.quote && (m.quote.body || m.quote.sender)){
      const quoteEl = document.createElement('div'); quoteEl.className = 'quote';
      if (m.quote.sender) quoteEl.appendChild(document.createTextNode(m.quote.sender + ': '));
      appendHighlighted(quoteEl, m.quote.body || '', q);
      wrap.appendChild(quoteEl);
    }
    if (m.body){
      const body = document.createElement('div');
      appendHighlighted(body, m.body, q);
      wrap.appendChild(body);
    }
    const atts = document.createElement('div'); atts.className = 'atts';
    (m.atts||[]).forEach(a => atts.appendChild(renderAttachment(a, resolve)));
    if (atts.children.length) wrap.appendChild(atts);
    if (m.caption){
      const cap = document.createElement('div');
      appendHighlighted(cap, m.caption, q);
      wrap.appendChild(cap);
    }
    (m.atts||[]).forEach(a => {
      if(a.caption){
        const cap = document.createElement('div');
        appendHighlighted(cap, a.caption, q);
        wrap.appendChild(cap);
      }
    });
    if (m.reactions && m.reactions.length){
      const rx = document.createElement('div'); rx.className = 'reactions';
      m.reactions.forEach(r => {
        const chip = document.createElement('span');
        chip.textContent = r.emoji || "";
        if (r.sender) chip.title = r.sender;
        rx.appendChild(chip);
      });
      wrap.appendChild(rx);
    }
    const clock = document.createElement('span');
    clock.className = 'clock';
    clock.textContent = timeText(m.ts) + (m.edited ? ' · edited' : '');
    wrap.appendChild(clock);
    container.appendChild(wrap);
  });
  if (focusTs){
    const el = container.querySelector('[data-ts="' + String(focusTs) + '"]');
    if (el){
      el.classList.add('focus');
      el.scrollIntoView({block:'center'});
      return;
    }
  }
  msgsEl.scrollTop = msgsEl.scrollHeight;
}

function renderList(list, el, active, onPick, resolve){
  el.innerHTML = '';
  list.forEach(t => {
    const li = document.createElement('li');
    if (active && (active.id === t.id || active.thread === t.thread)) li.classList.add('active');
    const copy = document.createElement('div'); copy.className = 'thread-copy';
    const nm = document.createElement('div'); nm.className = 'name'; nm.textContent = t.thread;
    const pv = document.createElement('div'); pv.className = 'preview'; pv.textContent = t.lastPreview || ((t.messages||[]).length + ' messages');
    copy.append(nm, pv);
    const meta = document.createElement('div'); meta.className = 'thread-meta';
    meta.textContent = shortDate(t.lastTs || ((t.messages||[])[(t.messages||[]).length-1]||{}).ts);
    li.append(liAvatar(t, resolve), copy, meta);
    li.onclick = () => onPick(t);
    el.appendChild(li);
  });
}

function renderHits(hits, q, el, section, onPick){
  if (!el) return;
  el.innerHTML = '';
  if (section) section.style.display = hits.length ? 'block' : 'none';
  hits.forEach(hit => {
    const li = document.createElement('li');
    const copy = document.createElement('div'); copy.className = 'thread-copy';
    const nm = document.createElement('div'); nm.className = 'name'; nm.textContent = hit.thread || 'Chat';
    const pv = document.createElement('div'); pv.className = 'preview';
    appendHighlighted(pv, snippet(hit.body, q), q);
    copy.append(nm, pv);
    const meta = document.createElement('div'); meta.className = 'thread-meta';
    meta.textContent = shortDate(hit.ts);
    const dot = document.createElement('div');
    dot.className = 'dot hit-dot';
    dot.textContent = '⌕';
    li.append(dot, copy, meta);
    li.onclick = () => onPick(hit);
    el.appendChild(li);
  });
}

function initViewer(opts){
  const data = opts.data || [];
  const resolve = opts.resolve || null;
  const knownEl = document.getElementById('known');
  const unknownEl = document.getElementById('unknown');
  const unkToggle = document.getElementById('unknown-toggle');
  const msgsEl = document.getElementById('msgs');
  const titleEl = document.getElementById('title');
  const countEl = document.getElementById('count');
  const qEl = document.getElementById('q');
  const stampEl = document.getElementById('stamp');
  const empty = document.getElementById('empty-hero');
  const hitsEl = document.getElementById('search-hits');
  const hitsSection = document.getElementById('search-hits-section');
  if (opts.meta && stampEl) stampEl.textContent = opts.meta.exportedOn ? ('Exported on ' + opts.meta.exportedOn) : '';
  if (qEl) qEl.placeholder = 'Search chats and messages';

  let active = null;
  let searchGen = 0;
  const pinnedEl = document.getElementById('pinned');
  const pinnedSection = document.getElementById('pinned-section');
  const pinned = data.filter(t => t.pinned);
  const known = data.filter(t => !t.pinned);
  const unknown = [];

  function showThread(t){
    if (empty) empty.style.display = 'none';
    if (msgsEl) msgsEl.style.display = 'block';
  }

  function currentQuery(){
    return (qEl && qEl.value || '').trim();
  }

  function pick(t, focusTs){
    active = t;
    showThread(t);
    refreshLists();
    const q = currentQuery();
    if (opts.loadThread){
      Promise.resolve(opts.loadThread(t)).then(full => renderThread(full || t, msgsEl, titleEl, countEl, resolve, focusTs, q));
    } else {
      renderThread(t, msgsEl, titleEl, countEl, resolve, focusTs, q);
    }
  }

  function pickHit(hit){
    const thread = data.find(t => String(t.id) === String(hit.threadId) || t.thread === hit.thread);
    if (thread) pick(thread, hit.ts);
  }

  function refreshLists(){
    const q = (qEl && qEl.value || '').trim();
    const qLower = q.toLowerCase();
    const match = t => !qLower || (t.thread||'').toLowerCase().includes(qLower) || (t.lastPreview||'').toLowerCase().includes(qLower);
    const pinnedHits = pinned.filter(match);
    if (pinnedEl){
      if (pinnedSection) pinnedSection.style.display = pinnedHits.length ? 'block' : 'none';
      renderList(pinnedHits, pinnedEl, active, pick, resolve);
    }
    renderList(known.filter(match), knownEl, active, pick, resolve);
    if (unknownEl && unknownEl.style.display !== 'none'){
      renderList(unknown.filter(match), unknownEl, active, pick, resolve);
    }
    loadMessageHits(q, qLower);
  }

  async function loadMessageHits(q, qLower){
    const gen = ++searchGen;
    if (!hitsEl) return;
    if (qLower.length < 2){
      renderHits([], qLower, hitsEl, hitsSection, pickHit);
      return;
    }
    let hits = [];
    if (opts.search){
      try{
        const res = await opts.search(q);
        hits = (res && res.hits) || [];
      }catch(e){
        hits = [];
      }
    } else {
      hits = localMessageHits(data, qLower).slice(0, 80);
    }
    if (gen !== searchGen) return;
    renderHits(hits, qLower, hitsEl, hitsSection, pickHit);
  }

  if (unkToggle && unknownEl){
    unkToggle.onclick = () => {
      const open = unknownEl.style.display === 'none';
      unknownEl.style.display = open ? 'block' : 'none';
      const section = document.getElementById('unknown-section');
      if (section) section.style.display = open ? 'block' : 'none';
      unkToggle.textContent = open ? 'Hide Unknown ▲' : 'Show Unknown ▼';
      refreshLists();
    };
  }
  if (qEl){
    let timer = null;
    qEl.oninput = () => {
      clearTimeout(timer);
      timer = setTimeout(refreshLists, opts.search ? 200 : 0);
    };
  }
  refreshLists();
  return { pick, refreshLists };
}
