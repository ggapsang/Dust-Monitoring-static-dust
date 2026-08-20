/* 화면.
 *
 * 상태는 서버가 갖는다. 여기서는 조회한 것을 그릴 뿐이고, 실패 사유의 한글
 * 표기도 만들지 않는다 - 판독 응답의 summary 에 이미 들어 있고, 같은 문구를
 * 두 곳에 두면 조용히 어긋난다. 필터·집계는 원문 사유로 한다.
 */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  targets: [],
  points: [],
  readings: [],
  selected: new Set(),
  order: 'captured_at',
  desc: true,
  uploads: [],
  poll: null,
};

// ── 통신 ────────────────────────────────────────────────────────────

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch { /* 본문 없음 */ }
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

function toast(message, bad = false) {
  const box = document.createElement('div');
  box.className = 'banner' + (bad ? ' bad' : '');
  box.innerHTML = `<strong>${bad ? '실패' : '완료'}</strong> ${escape(message)}`;
  $('main').prepend(box);
  setTimeout(() => box.remove(), 6000);
}

const escape = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (ch) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);

const num = (value, digits = 3) =>
  value === null || value === undefined ? '—' : Number(value).toFixed(digits);

const stamp = (iso) => {
  if (!iso) return '—';
  const at = new Date(iso);
  const pad = (n) => String(n).padStart(2, '0');
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
};

// ── 라우팅 ──────────────────────────────────────────────────────────

function route() {
  const name = (location.hash || '#results').slice(1);
  $$('section.view').forEach((node) => node.classList.toggle('on', node.id === `view-${name}`));
  $$('nav a').forEach((node) => node.classList.toggle('on', node.dataset.view === name));
}
window.addEventListener('hashchange', route);

// ── 결과 스프레드시트 ───────────────────────────────────────────────

function query() {
  const params = new URLSearchParams();
  const put = (key, value) => { if (value) params.set(key, value); };
  put('target_id', $('#f-target').value);
  put('point_id', $('#f-point').value);
  put('success', $('#f-success').value);
  put('failure_reason', $('#f-reason').value);
  put('run_kind', $('#f-kind').value);
  if ($('#f-since').value) params.set('since', `${$('#f-since').value}T00:00:00`);
  if ($('#f-until').value) params.set('until', `${$('#f-until').value}T23:59:59`);
  return params;
}

async function loadReadings() {
  const params = query();
  params.set('order', state.order);
  params.set('desc', String(state.desc));
  state.readings = await api(`/api/readings?${params}`);
  drawReadings();
  fillReasons();
}

function drawReadings() {
  const body = $('#t-readings tbody');
  body.innerHTML = state.readings.map((row) => {
    const badge = row.success
      ? '<span class="badge ok"><i class="dot"></i>성공</span>'
      : `<span class="badge bad" title="${escape(row.summary)}"><i class="dot"></i>${escape(row.failure_reason || '실패')}</span>`;
    const mark = row.read_point_id && row.point_id && row.read_point_id !== row.point_id
      ? ' <span class="badge warn" title="판독 번호가 짝지어진 개소와 다르다"><i class="dot"></i>불일치</span>'
      : '';
    return `<tr data-id="${row.id}" class="${state.selected.has(row.id) ? 'sel' : ''}">
      <td><input type="checkbox" data-pick="${row.id}" ${state.selected.has(row.id) ? 'checked' : ''}></td>
      <td>${stamp(row.captured_at)}</td>
      <td>${escape(row.target_id)}</td>
      <td class="key">${escape(row.point_id || '—')}</td>
      <td class="num">${row.sequence ?? '—'}</td>
      <td>${badge}</td>
      <td class="num">${num(row.score_uniform)}</td>
      <td class="num">${num(row.score_localized)}</td>
      <td class="num key">${num(row.score_combined)}</td>
      <td class="num">${num(row.quality_sharpness, 4)}</td>
      <td class="num">${num(row.quality_saturated_ratio, 4)}</td>
      <td class="num">${num(row.quality_pad_size_px, 1)}</td>
      <td class="num">${num(row.quality_pad_size_diff_ratio, 4)}</td>
      <td>${escape(row.read_point_id || '—')}${mark}</td>
      <td class="num">${num(row.elapsed_ms, 0)}</td>
      <td>${row.run_kind === 'rerun' ? '<span class="badge info"><i class="dot"></i>재판독</span>' : '최초'}${row.has_override ? ' <span class="badge info"><i class="dot"></i>설정</span>' : ''}</td>
    </tr>`;
  }).join('');

  $('#results-empty').style.display = state.readings.length ? 'none' : 'block';
  $('#f-rerun').disabled = state.selected.size === 0;

  $$('#t-readings tbody tr').forEach((tr) => {
    tr.addEventListener('click', (event) => {
      if (event.target.dataset.pick) return;
      openDetail(Number(tr.dataset.id));
    });
  });
  $$('[data-pick]').forEach((box) => {
    box.addEventListener('change', () => {
      const id = Number(box.dataset.pick);
      box.checked ? state.selected.add(id) : state.selected.delete(id);
      box.closest('tr').classList.toggle('sel', box.checked);
      $('#f-rerun').disabled = state.selected.size === 0;
    });
  });
}

function fillReasons() {
  const reasons = [...new Set(state.readings.map((r) => r.failure_reason).filter(Boolean))];
  const select = $('#f-reason');
  const keep = select.value;
  select.innerHTML = '<option value="">전체</option>' +
    reasons.map((r) => `<option value="${escape(r)}">${escape(r)}</option>`).join('');
  select.value = keep;
}

// ── 상세 ────────────────────────────────────────────────────────────

async function openDetail(id) {
  const row = await api(`/api/readings/${id}`);
  location.hash = '#detail';
  $('#d-body').innerHTML = detailCard(row, true);
}

function detailCard(row, full) {
  const shot = (src, caption) =>
    src ? `<figure class="shot"><img src="${src}" loading="lazy"><figcaption>${caption}</figcaption></figure>` : '';
  const images = row.images || {};
  const override = full && row.config_override && Object.keys(row.config_override).length
    ? `<p class="muted">적용된 설정 오버라이드 <code>${escape(JSON.stringify(row.config_override))}</code></p>` : '';
  return `<div class="card">
    <div class="row" style="justify-content:space-between">
      <h3>${escape(row.point_id || '개소 미상')} · ${row.sequence ? `${row.sequence}회차` : ''} · ${stamp(row.captured_at)}</h3>
      <div>${row.success
        ? `<span class="badge ok"><i class="dot"></i>total ${num(row.score_combined)}</span>`
        : `<span class="badge bad"><i class="dot"></i>${escape(row.failure_reason || '실패')}</span>`}</div>
    </div>
    <p class="muted">${escape(row.summary || '')}</p>
    ${override}
    <div class="shots">
      ${shot(row.baseline_image, '기준 사진 원본')}
      ${shot(row.capture_image, '판독 사진 원본')}
      ${shot(images.baseline_rectified, '기준 정합')}
      ${shot(images.rectified, '판독 정합')}
      ${shot(images.distribution, '오염도 분포')}
    </div>
    ${full ? `<div class="row" style="margin-top:12px">
      <button class="secondary" data-rerun="${row.id}">이 건 재판독</button>
    </div>` : ''}
  </div>`;
}

async function loadStack() {
  const point = $('#d-point').value;
  if (!point) return;
  const mode = $('#d-mode').value;
  const rows = await api(`/api/readings?point_id=${encodeURIComponent(point)}&order=captured_at&desc=false&limit=200`);
  if (!rows.length) { $('#d-body').innerHTML = '<div class="card empty">판독 결과가 없다.</div>'; return; }
  const list = mode === 'one' ? rows.slice(-1) : rows;
  $('#d-body').innerHTML = list.map((row) => detailCard(row, false)).join('');
}

// ── 시계열 ──────────────────────────────────────────────────────────

async function loadSeries() {
  const point = $('#s-point').value;
  if (!point) return;
  const params = new URLSearchParams({ metric: $('#s-metric').value, slack: $('#s-slack').value || '0' });
  if ($('#s-n').value) params.set('mad_n', $('#s-n').value);
  const data = await api(`/api/series/${encodeURIComponent(point)}?${params}`);
  if (!data.points.length) { $('#s-body').innerHTML = '<div class="card empty">판독 결과가 없다.</div>'; return; }

  $('#s-body').innerHTML = `
    <div class="card"><h3>절대량 · 기준 대비 지금까지 쌓인 총량</h3>
      ${lineChart(data.points.map((p) => p.absolute), data.points.map((p) => p.sequence))}</div>
    <div class="card"><h3>추세 · 직전 회차 대비 증분</h3>
      ${lineChart(data.points.map((p) => p.delta), data.points.map((p) => p.sequence), data.limit)}
      <p class="muted">증분 중앙값 ${num(data.delta_median, 4)} · MAD ${num(data.delta_mad, 4)}${data.limit === null ? ' · 경계 배수 n 을 넣으면 경계선을 그린다' : ` · 경계 ${num(data.limit, 4)}`}</p></div>
    <div class="card"><h3>누적 · 증분에서 여유를 뺀 값의 합</h3>
      ${lineChart(data.points.map((p) => p.cusum), data.points.map((p) => p.sequence), null, true)}</div>`;
}

function lineChart(values, labels, limit = null, alt = false) {
  const width = 900, height = 240, pad = 36;
  const clean = values.map((v) => (v === null || v === undefined ? null : Number(v)));
  const known = clean.filter((v) => v !== null);
  if (!known.length) return '<div class="empty">그릴 값이 없다.</div>';
  let low = Math.min(...known, limit ?? Infinity);
  let high = Math.max(...known, limit ?? -Infinity);
  if (high === low) { high = low + 1; }
  const x = (i) => pad + (i * (width - pad * 2)) / Math.max(1, clean.length - 1);
  const y = (v) => height - pad - ((v - low) * (height - pad * 2)) / (high - low);

  const path = clean.map((v, i) => (v === null ? null : `${x(i)},${y(v)}`))
    .filter(Boolean).join(' ');
  const dots = clean.map((v, i) => (v === null ? '' :
    `<circle class="dot" cx="${x(i)}" cy="${y(v)}" r="3"><title>${labels[i]}회차 ${num(v, 4)}</title></circle>`)).join('');
  const limitLine = limit === null || limit === undefined ? '' :
    `<line class="limit" x1="${pad}" y1="${y(limit)}" x2="${width - pad}" y2="${y(limit)}"></line>`;

  return `<svg class="chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
    <line class="grid" x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}"></line>
    <line class="grid" x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}"></line>
    <text class="axis" x="4" y="${pad + 4}">${num(high, 3)}</text>
    <text class="axis" x="4" y="${height - pad}">${num(low, 3)}</text>
    ${limitLine}
    <polyline class="line ${alt ? 'alt' : ''}" points="${path}"></polyline>
    ${dots}
  </svg>`;
}

// ── 분포 ────────────────────────────────────────────────────────────

async function loadDistribution() {
  const params = new URLSearchParams({ metric: $('#x-metric').value, bins: $('#x-bins').value });
  if ($('#x-point').value) params.set('point_id', $('#x-point').value);
  const data = await api(`/api/distribution?${params}`);
  if (!data.count) { $('#x-body').innerHTML = '<div class="card empty">값이 없다.</div>'; return; }

  const reasons = Object.entries(data.failure_counts || {});
  $('#x-body').innerHTML = `
    <div class="card">
      <h3>${escape(data.metric)}</h3>
      ${histogram(data)}
      <div class="legend">
        <span><i style="background:var(--status-success-solid)"></i>성공</span>
        <span><i style="background:var(--status-error-solid)"></i>실패</span>
      </div>
      <p class="muted">건수 ${data.count} · 최소 ${num(data.minimum, 4)} · 중앙 ${num(data.median, 4)} · 최대 ${num(data.maximum, 4)}</p>
      <p class="muted">산출값은 게이트 통과 여부와 무관하게 항상 나온다. 어느 값에서 실패가 갈리는지 보려고 같은 축에 겹쳐 센다.</p>
    </div>
    ${reasons.length ? `<div class="card"><h3>실패 사유별 건수</h3>
      <table><tbody>${reasons.map(([k, v]) => `<tr><td>${escape(k)}</td><td class="num">${v}</td></tr>`).join('')}</tbody></table></div>` : ''}`;
}

function histogram(data) {
  const width = 900, height = 240, pad = 36;
  const peak = Math.max(...data.bins.map((b) => b.success + b.failure), 1);
  const step = (width - pad * 2) / data.bins.length;
  const bars = data.bins.map((bin, index) => {
    const x = pad + index * step;
    const okHeight = ((height - pad * 2) * bin.success) / peak;
    const badHeight = ((height - pad * 2) * bin.failure) / peak;
    const title = `${num(bin.start, 4)}~${num(bin.end, 4)} · 성공 ${bin.success} · 실패 ${bin.failure}`;
    return `<g><title>${title}</title>
      <rect class="bar-bad" x="${x + 1}" y="${height - pad - badHeight}" width="${step - 2}" height="${badHeight}"></rect>
      <rect class="bar-ok" x="${x + 1}" y="${height - pad - badHeight - okHeight}" width="${step - 2}" height="${okHeight}"></rect>
    </g>`;
  }).join('');
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
    <line class="grid" x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}"></line>
    <text class="axis" x="4" y="${pad + 4}">${peak}</text>
    <text class="axis" x="${pad}" y="${height - 12}">${num(data.minimum, 3)}</text>
    <text class="axis" x="${width - pad - 40}" y="${height - 12}">${num(data.maximum, 3)}</text>
    ${bars}
  </svg>`;
}

// ── 판독 실행 ───────────────────────────────────────────────────────

async function pickFiles() {
  const files = [...$('#r-files').files];
  if (!files.length) { state.uploads = []; drawUploads(); return; }
  const parsed = await api('/api/uploads/parse?kind=capture', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(files.map((f) => f.name)),
  });
  state.uploads = parsed.map((row, index) => ({
    ...row,
    file: files[index],
    target_id: row.target_id || '',
    stamp: row.stamp || '',
  }));
  drawUploads();
}

function drawUploads() {
  const body = $('#t-uploads tbody');
  body.innerHTML = state.uploads.map((row, index) => {
    const options = state.targets
      .map((t) => `<option value="${escape(t.target_id)}" ${t.target_id === row.target_id ? 'selected' : ''}>${escape(t.target_id)}</option>`)
      .join('');
    const badge = row.parsed && row.known_id
      ? '<span class="badge ok"><i class="dot"></i>자동</span>'
      : `<span class="badge warn"><i class="dot"></i>${escape(row.message || '직접 지정')}</span>`;
    const local = row.stamp ? new Date(row.stamp).toISOString().slice(0, 16) : '';
    return `<tr>
      <td>${escape(row.filename)}</td>
      <td><select data-target="${index}"><option value="">선택</option>${options}</select></td>
      <td><input type="datetime-local" data-stamp="${index}" value="${local}"></td>
      <td>${badge}</td>
    </tr>`;
  }).join('');

  $$('[data-target]').forEach((node) => node.addEventListener('change', () => {
    state.uploads[Number(node.dataset.target)].target_id = node.value;
    $('#r-go').disabled = !ready();
  }));
  $$('[data-stamp]').forEach((node) => node.addEventListener('change', () => {
    state.uploads[Number(node.dataset.stamp)].stamp = node.value;
    $('#r-go').disabled = !ready();
  }));
  $('#r-go').disabled = !ready();
}

const ready = () => state.uploads.length > 0 && state.uploads.every((row) => row.target_id && row.stamp);

async function startRun() {
  const form = new FormData();
  state.uploads.forEach((row) => form.append('files', row.file, row.filename));
  form.append('target_ids', JSON.stringify(state.uploads.map((r) => r.target_id)));
  form.append('captured_ats', JSON.stringify(state.uploads.map((r) => r.stamp)));
  form.append('config_override', $('#r-override').value.trim());

  $('#r-go').disabled = true;
  try {
    const run = await api('/api/runs', { method: 'POST', body: form });
    $('#r-progress').style.display = 'block';
    watch(run.id);
  } catch (error) {
    toast(error.message, true);
    $('#r-go').disabled = false;
  }
}

function watch(runId) {
  clearInterval(state.poll);
  const tick = async () => {
    const run = await api(`/api/runs/${runId}`);
    const done = run.status !== 'running';
    $('#r-status').innerHTML = `
      <div class="row">
        <span class="badge ${done ? 'ok' : 'info'}"><i class="dot"></i>${done ? '완료' : '판독 중'}</span>
        <span>사진 ${run.done_captures} / ${run.total_captures} · 결과 ${run.reading_count}건</span>
      </div>
      ${(run.notes || []).map((n) => `<div class="banner"><strong>${escape(n.kind)}</strong> ${escape(n.message)}</div>`).join('')}`;
    if (done) {
      clearInterval(state.poll);
      $('#r-go').disabled = false;
      await Promise.all([loadReadings(), loadRuns()]);
    }
  };
  tick();
  state.poll = setInterval(tick, 2000);
}

async function loadRuns() {
  const runs = await api('/api/runs?limit=20');
  $('#t-runs tbody').innerHTML = runs.map((run) => `<tr>
    <td>${run.id}</td><td>${stamp(run.executed_at)}</td>
    <td>${run.kind === 'rerun' ? '재판독' : '최초'}</td>
    <td><span class="badge ${run.status === 'done' ? 'ok' : run.status === 'failed' ? 'bad' : 'info'}"><i class="dot"></i>${escape(run.status)}</span></td>
    <td class="num">${run.done_captures}/${run.total_captures}</td>
    <td class="num">${run.reading_count}</td>
    <td>${(run.notes || []).length}</td>
  </tr>`).join('');
}

// ── 등록 ────────────────────────────────────────────────────────────

async function loadRegistry() {
  [state.targets, state.points] = await Promise.all([api('/api/targets'), api('/api/points')]);

  const targetOptions = state.targets
    .map((t) => `<option value="${escape(t.target_id)}">${escape(t.target_id)}${t.name ? ` · ${escape(t.name)}` : ''}</option>`).join('');
  const pointOptions = state.points
    .map((p) => `<option value="${escape(p.point_id)}">${escape(p.point_id)}${p.name ? ` · ${escape(p.name)}` : ''}</option>`).join('');

  $('#n-point-target').innerHTML = targetOptions;
  $('#f-target').innerHTML = '<option value="">전체</option>' + targetOptions;
  ['#f-point', '#x-point'].forEach((sel) => { $(sel).innerHTML = '<option value="">전체</option>' + pointOptions; });
  ['#d-point', '#s-point'].forEach((sel) => { $(sel).innerHTML = '<option value="">선택</option>' + pointOptions; });
  $('#b-point').innerHTML = '<option value="">파일명에서</option>' + pointOptions;

  const baselines = await api('/api/baselines');
  const byPoint = {};
  baselines.forEach((b) => { (byPoint[b.point_id] ||= []).push(b); });

  $('#tree').innerHTML = state.targets.map((target) => {
    const children = state.points.filter((p) => p.target_id === target.target_id);
    return `<li>
      <strong>${escape(target.target_id)}</strong>
      <span class="muted">${escape(target.name || '')} ${escape(target.location_desc || '')}</span>
      <ul>${children.length ? children.map((point) => {
        const list = byPoint[point.point_id] || [];
        const current = list.find((b) => b.is_current);
        return `<li>
          <span class="key">${escape(point.point_id)}</span>
          <span class="muted">${escape(point.name || '')}</span>
          <span class="badge info"><i class="dot"></i>${escape(point.tone)}</span>
          ${current
            ? `<span class="badge ok"><i class="dot"></i>기준 ${stamp(current.effective_from)}</span>`
            : '<span class="badge warn"><i class="dot"></i>기준 없음</span>'}
          ${list.length > 1 ? `<span class="muted">이력 ${list.length}건</span>` : ''}
        </li>`;
      }).join('') : '<li class="muted">등록된 개소가 없다</li>'}</ul>
    </li>`;
  }).join('') || '<li class="muted">등록된 촬영 단위가 없다</li>';
}

// ── 붙이기 ──────────────────────────────────────────────────────────

function bind() {
  $('#theme').addEventListener('click', () => {
    const now = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = now;
    $('#theme').textContent = now === 'dark' ? '라이트' : '다크';
    localStorage.setItem('padlab-theme', now);
  });

  $('#f-apply').addEventListener('click', () => loadReadings().catch((e) => toast(e.message, true)));
  $('#f-csv').addEventListener('click', () => { location.href = `/api/readings/export.csv?${query()}`; });
  $('#f-rerun').addEventListener('click', async () => {
    const override = prompt('재판독에 적용할 설정 오버라이드 (JSON). 비우면 서버 설정 그대로.', '{}');
    if (override === null) return;
    try {
      const run = await api('/api/readings/rerun', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reading_ids: [...state.selected], config_override: JSON.parse(override || '{}') }),
      });
      state.selected.clear();
      location.hash = '#run';
      $('#r-progress').style.display = 'block';
      watch(run.id);
    } catch (error) { toast(error.message, true); }
  });

  $$('#t-readings thead th[data-sort]').forEach((th) => th.addEventListener('click', () => {
    const key = th.dataset.sort;
    state.desc = state.order === key ? !state.desc : true;
    state.order = key;
    loadReadings().catch((e) => toast(e.message, true));
  }));

  $('#r-files').addEventListener('change', () => pickFiles().catch((e) => toast(e.message, true)));
  $('#r-go').addEventListener('click', startRun);

  $('#d-load').addEventListener('click', () => loadStack().catch((e) => toast(e.message, true)));
  $('#s-load').addEventListener('click', () => loadSeries().catch((e) => toast(e.message, true)));
  $('#x-load').addEventListener('click', () => loadDistribution().catch((e) => toast(e.message, true)));

  document.addEventListener('click', async (event) => {
    const id = event.target.dataset?.rerun;
    if (!id) return;
    try {
      const run = await api('/api/readings/rerun', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reading_ids: [Number(id)], config_override: {} }),
      });
      location.hash = '#run';
      $('#r-progress').style.display = 'block';
      watch(run.id);
    } catch (error) { toast(error.message, true); }
  });

  $('#n-target-go').addEventListener('click', async () => {
    try {
      await api('/api/targets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_id: $('#n-target-id').value.trim(),
          name: $('#n-target-name').value.trim() || null,
          location_desc: $('#n-target-loc').value.trim() || null,
        }),
      });
      $('#n-target-id').value = $('#n-target-name').value = $('#n-target-loc').value = '';
      await loadRegistry();
      toast('촬영 단위를 추가했다');
    } catch (error) { toast(error.message, true); }
  });

  $('#n-point-go').addEventListener('click', async () => {
    try {
      await api('/api/points', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          point_id: $('#n-point-id').value.trim(),
          target_id: $('#n-point-target').value,
          name: $('#n-point-name').value.trim() || null,
          location_desc: $('#n-point-loc').value.trim() || null,
          tone: $('#n-point-tone').value,
        }),
      });
      $('#n-point-id').value = $('#n-point-name').value = $('#n-point-loc').value = '';
      await loadRegistry();
      toast('개소를 추가했다');
    } catch (error) { toast(error.message, true); }
  });

  $('#b-go').addEventListener('click', async () => {
    const file = $('#b-file').files[0];
    if (!file) { toast('파일을 고른다', true); return; }
    const form = new FormData();
    form.append('file', file, file.name);
    if ($('#b-point').value) form.append('point_id', $('#b-point').value);
    if ($('#b-when').value) form.append('effective_from', $('#b-when').value);
    try {
      await api('/api/baselines', { method: 'POST', body: form });
      $('#b-file').value = '';
      await loadRegistry();
      toast('기준 사진을 등록했다');
    } catch (error) { toast(error.message, true); }
  });
}

async function boot() {
  // 기본은 라이트다. 디자인 시스템의 기본값은 다크지만 이 화면은 사무실
  // 주간 사용이라 라이트로 연다. 고른 값은 브라우저에 남는다.
  const saved = localStorage.getItem('padlab-theme');
  document.documentElement.dataset.theme = saved || 'light';
  $('#theme').textContent = document.documentElement.dataset.theme === 'dark' ? '라이트' : '다크';

  bind();
  route();
  try {
    const config = await api('/api/reader/config');
    $('#reader-state').className = 'badge ok';
    $('#reader-state').innerHTML = `<i class="dot"></i>판독기 연결 · ${escape(config.source ? '설정 파일' : '내장 기본값')}`;
  } catch {
    $('#reader-state').className = 'badge bad';
    $('#reader-state').innerHTML = '<i class="dot"></i>판독기 응답 없음';
  }
  await loadRegistry();
  await Promise.all([loadReadings(), loadRuns()]);
}

boot().catch((error) => toast(error.message, true));
