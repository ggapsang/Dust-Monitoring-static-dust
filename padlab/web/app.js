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
  // 열마다의 필터와 정렬. 엑셀처럼 열 이름을 눌러 정한다.
  colFilters: {},
  // 정렬 키를 순서대로 담는다. 앞의 것이 우선이고, 값이 같을 때 뒤의 것으로
  // 가른다. 하나만 담으면 단일 정렬과 같다.
  sort: [{ key: 'captured_at', desc: true }],
  menu: null,
  uploads: [],
  poll: null,
  // 등록 화면에서 지금 고치고 있는 행. {kind, id} 하나만 둔다 - 여러 행을
  // 동시에 열어 두면 어느 것을 저장하는지 헷갈린다.
  edit: null,
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
//
// 열 정의를 한 곳에 모은다. 머리글과 본문을 따로 적으면 열을 하나 넣고
// 빼는 순간 둘이 어긋나고, 그러면 값이 엉뚱한 칸에 실려 보인다.
//
// 거르기와 정렬은 받아 온 목록 안에서 한다. 서버로 매번 다시 물으면 열을
// 누를 때마다 기다려야 하고, 실증 규모에서는 그럴 이유가 없다. 기간만
// 서버에 넘겨 가져올 범위를 정한다.

const COLUMNS = [
  { key: 'captured_at', label: '촬영 일시', kind: 'date',
    face: (r) => (r.captured_at || '').slice(0, 10),
    cell: (r) => stamp(r.captured_at) },
  { key: 'target_id', label: 'TARGET_ID', kind: 'text' },
  { key: 'point_id', label: '개소', kind: 'text', cls: 'key' },
  { key: 'sequence', label: '회차', kind: 'num', digits: 0 },
  { key: 'status', label: '상태', kind: 'text',
    get: (r) => (r.success ? '성공' : (r.failure_reason || '실패')),
    cell: (r) => (r.success
      ? '<span class="badge ok"><i class="dot"></i>성공</span>'
      : `<span class="badge bad" title="${escape(r.summary)}"><i class="dot"></i>${escape(r.failure_reason || '실패')}</span>`) },
  { key: 'score_uniform', label: 'uniform', kind: 'num', digits: 3 },
  { key: 'score_localized', label: 'localized', kind: 'num', digits: 3 },
  { key: 'score_combined', label: 'total', kind: 'num', digits: 3, cls: 'key' },
  { key: 'quality_sharpness', label: '선명도', kind: 'num', digits: 4 },
  { key: 'quality_saturated_ratio', label: '포화', kind: 'num', digits: 4 },
  { key: 'quality_pad_size_px', label: '패드 크기', kind: 'num', digits: 1 },
  { key: 'quality_pad_size_diff_ratio', label: '크기 차이', kind: 'num', digits: 4 },
  { key: 'read_point_id', label: '판독 번호', kind: 'text',
    cell: (r) => `${escape(r.read_point_id || '—')}${r.read_point_id && r.point_id && r.read_point_id !== r.point_id
      ? ' <span class="badge warn" title="판독 번호가 짝지어진 개소와 다르다"><i class="dot"></i>불일치</span>' : ''}` },
  { key: 'elapsed_ms', label: '처리(ms)', kind: 'num', digits: 0 },
  { key: 'run_kind', label: '실행', kind: 'text',
    get: (r) => (r.run_kind === 'rerun' ? '재판독' : '최초'),
    cell: (r) => `${r.run_kind === 'rerun'
      ? '<span class="badge info"><i class="dot"></i>재판독</span>'
      : '<span class="badge neutral"><i class="dot"></i>최초</span>'}${r.has_override
      ? ' <span class="badge info"><i class="dot"></i>설정</span>' : ''}` },
];

const raw = (column, row) => (column.get ? column.get(row) : row[column.key]);
const face = (column, row) => {
  if (column.face) return column.face(row);
  const value = raw(column, row);
  return value === null || value === undefined || value === '' ? '' : String(value);
};

/** 기간만 서버에 넘긴다. 나머지는 받아 온 목록 안에서 거른다. */
function query() {
  const params = new URLSearchParams();
  if ($('#f-since').value) params.set('since', `${$('#f-since').value}T00:00:00`);
  if ($('#f-until').value) params.set('until', `${$('#f-until').value}T23:59:59`);
  return params;
}

async function loadReadings() {
  const params = query();
  params.set('limit', '5000');
  state.readings = await api(`/api/readings?${params}`);
  drawReadings();
}

/** 열 필터를 통과한 행. 정렬까지 마친 것이다. */
function visibleRows() {
  let rows = state.readings.filter((row) =>
    COLUMNS.every((column) => {
      const rule = state.colFilters[column.key];
      if (!rule) return true;
      if (rule.values) return rule.values.has(face(column, row));
      const value = raw(column, row);
      if (value === null || value === undefined) return false;
      if (rule.min !== null && Number(value) < rule.min) return false;
      if (rule.max !== null && Number(value) > rule.max) return false;
      return true;
    }));

  if (state.sort.length) {
    rows = [...rows].sort((left, right) => {
      for (const key of state.sort) {
        const column = COLUMNS.find((c) => c.key === key.key);
        if (!column) continue;
        const diff = compare(column, raw(column, left), raw(column, right), key.desc);
        if (diff) return diff;
      }
      return 0;
    });
  }
  return rows;
}

/** 값 두 개의 앞뒤. 같으면 0 이라 다음 정렬 키로 넘어간다. */
function compare(column, x, y, desc) {
  const blank = (v) => v === null || v === undefined || v === '';
  // 빈 값은 방향과 무관하게 뒤로 보낸다. 섞여 들어오면 정렬한 의미가 없다.
  if (blank(x) && blank(y)) return 0;
  if (blank(x)) return 1;
  if (blank(y)) return -1;
  const diff = column.kind === 'num'
    ? Number(x) - Number(y)
    : String(x).localeCompare(String(y), 'ko');
  return desc ? -diff : diff;
}

function drawReadings() {
  $('#t-head').innerHTML = '<th class="plain"></th>' + COLUMNS.map((column, index) => {
    const rank = state.sort.findIndex((k) => k.key === column.key);
    const filtered = Boolean(state.colFilters[column.key]);
    // 정렬이 둘 이상이면 순번을 같이 낸다. 무엇이 먼저인지 안 보이면 왜 이
    // 순서로 늘어섰는지 알 수 없다.
    const mark = `${rank < 0 ? '' : (state.sort[rank].desc ? '▼' : '▲')
      + (state.sort.length > 1 ? rank + 1 : '')}${filtered ? '●' : ''}`;
    // 촬영 일시만 왼쪽에 두고 그 뒤는 전부 가운데로 맞춘다. 열마다 정렬이
    // 다르면 값이 어느 열 것인지 눈으로 좇기 어렵다.
    return `<th class="${column.kind === 'num' ? 'num ' : ''}${index ? 'mid ' : ''}${rank >= 0 || filtered ? 'picked' : ''}"
      data-col="${column.key}">${escape(column.label)}<span class="mark">${mark}</span></th>`;
  }).join('');

  const rows = visibleRows();
  $('#t-readings tbody').innerHTML = rows.map((row) => `<tr data-id="${row.id}" class="${state.selected.has(row.id) ? 'sel' : ''}">
      <td><input type="checkbox" data-pick="${row.id}" ${state.selected.has(row.id) ? 'checked' : ''}></td>
      ${COLUMNS.map((column, index) => {
        const body = column.cell
          ? column.cell(row)
          : (column.kind === 'num' ? num(raw(column, row), column.digits) : escape(face(column, row) || '—'));
        return `<td class="${column.kind === 'num' ? 'num ' : ''}${index ? 'mid ' : ''}${column.cls || ''}">${body}</td>`;
      }).join('')}
    </tr>`).join('');

  const hidden = state.readings.length - rows.length;
  const order = state.sort
    .map((key) => {
      const column = COLUMNS.find((c) => c.key === key.key);
      return column ? `${column.label} ${key.desc ? '▼' : '▲'}` : '';
    })
    .filter(Boolean)
    .join(' → ');
  $('#f-count').textContent = state.readings.length
    ? `${rows.length}건${hidden ? ` (필터로 ${hidden}건 숨김)` : ''}${order ? ` · 정렬 ${order}` : ''}`
    : '';
  $('#results-empty').style.display = state.readings.length ? 'none' : 'block';
  $('#f-rerun').disabled = $('#f-delete').disabled = state.selected.size === 0;

  $$('#t-readings tbody tr').forEach((tr) => tr.addEventListener('click', (event) => {
    if (event.target.dataset.pick) return;
    openDetail(Number(tr.dataset.id));
  }));
  $$('[data-pick]').forEach((box) => box.addEventListener('change', () => {
    const id = Number(box.dataset.pick);
    box.checked ? state.selected.add(id) : state.selected.delete(id);
    box.closest('tr').classList.toggle('sel', box.checked);
    $('#f-rerun').disabled = $('#f-delete').disabled = state.selected.size === 0;
  }));
  $$('#t-head th[data-col]').forEach((th) => th.addEventListener('click', (event) => {
    event.stopPropagation();
    openColumnMenu(th, COLUMNS.find((c) => c.key === th.dataset.col));
  }));
}

/** 열 하나의 정렬·필터 메뉴. 한 번에 하나만 떠 있다. */
function openColumnMenu(th, column) {
  closeColumnMenu();
  const menu = document.createElement('div');
  menu.className = 'colmenu';

  const rule = state.colFilters[column.key];
  const body = column.kind === 'num'
    ? `<div class="range">
         <label class="field">이상<input type="number" step="any" data-min value="${rule && rule.min !== null ? rule.min : ''}"></label>
         <label class="field">이하<input type="number" step="any" data-max value="${rule && rule.max !== null ? rule.max : ''}"></label>
       </div>`
    : (() => {
        // 지금 화면에 있는 값만 보여 준다. 다른 열에서 이미 걸러 낸 값을
        // 고르게 하면 아무리 눌러도 아무 행도 안 남는다.
        const pool = state.readings.filter((row) => COLUMNS.every((other) => {
          if (other.key === column.key) return true;
          const r = state.colFilters[other.key];
          if (!r) return true;
          if (r.values) return r.values.has(face(other, row));
          const v = raw(other, row);
          if (v === null || v === undefined) return false;
          return (r.min === null || Number(v) >= r.min) && (r.max === null || Number(v) <= r.max);
        }));
        const values = [...new Set(pool.map((row) => face(column, row)))].sort((a, b) => a.localeCompare(b, 'ko'));
        const on = (value) => (!rule || !rule.values || rule.values.has(value) ? 'checked' : '');
        return `<input type="text" data-search placeholder="값 검색">
          <div class="sect">${values.map((value) => `
            <label class="opt"><input type="checkbox" data-value="${escape(value)}" ${on(value)}>
              <span>${escape(value || '(빈 값)')}</span></label>`).join('')
          || '<div class="opt muted">값이 없다</div>'}</div>`;
      })();

  const rank = state.sort.findIndex((k) => k.key === column.key);
  menu.innerHTML = `
    <div class="opt" data-sort-asc>오름차순 정렬</div>
    <div class="opt" data-sort-desc>내림차순 정렬</div>
    <div class="opt" data-add-asc>정렬에 추가 · 오름차순</div>
    <div class="opt" data-add-desc>정렬에 추가 · 내림차순</div>
    ${rank >= 0 ? `<div class="opt" data-unsort>이 열 정렬 해제 (지금 ${rank + 1}순위)</div>` : ''}
    <hr>
    ${body}
    <div class="foot">
      <button class="ghost tiny" data-clear>이 열 필터 해제</button>
      <button class="primary tiny" data-apply>적용</button>
    </div>`;

  document.body.appendChild(menu);
  const box = th.getBoundingClientRect();
  menu.style.left = `${Math.min(box.left + window.scrollX, window.innerWidth - menu.offsetWidth - 8)}px`;
  menu.style.top = `${box.bottom + window.scrollY + 4}px`;
  state.menu = menu;

  const search = $('[data-search]', menu);
  if (search) {
    search.focus();
    search.addEventListener('input', () => {
      const needle = search.value.trim().toLowerCase();
      $$('.opt', menu).forEach((opt) => {
        const box2 = $('[data-value]', opt);
        if (!box2) return;
        opt.style.display = box2.dataset.value.toLowerCase().includes(needle) ? '' : 'none';
      });
    });
  }

  menu.addEventListener('click', (event) => {
    event.stopPropagation();
    const target = event.target;
    if (target.closest('[data-sort-asc]')) { state.sort = [{ key: column.key, desc: false }]; closeColumnMenu(); drawReadings(); }
    else if (target.closest('[data-sort-desc]')) { state.sort = [{ key: column.key, desc: true }]; closeColumnMenu(); drawReadings(); }
    else if (target.closest('[data-add-asc]')) { addSort(column.key, false); closeColumnMenu(); drawReadings(); }
    else if (target.closest('[data-add-desc]')) { addSort(column.key, true); closeColumnMenu(); drawReadings(); }
    else if (target.closest('[data-unsort]')) { state.sort = state.sort.filter((k) => k.key !== column.key); closeColumnMenu(); drawReadings(); }
    else if (target.closest('[data-clear]')) { delete state.colFilters[column.key]; closeColumnMenu(); drawReadings(); }
    else if (target.closest('[data-apply]')) { applyColumnFilter(menu, column); closeColumnMenu(); drawReadings(); }
  });
}

/** 정렬 키를 뒤에 붙인다. 이미 있으면 방향만 바꾸고 순번은 지킨다. */
function addSort(key, desc) {
  const found = state.sort.find((k) => k.key === key);
  if (found) found.desc = desc;
  else state.sort.push({ key, desc });
}

function applyColumnFilter(menu, column) {
  if (column.kind === 'num') {
    const min = $('[data-min]', menu).value;
    const max = $('[data-max]', menu).value;
    if (min === '' && max === '') delete state.colFilters[column.key];
    else state.colFilters[column.key] = { min: min === '' ? null : Number(min), max: max === '' ? null : Number(max) };
    return;
  }
  const boxes = $$('[data-value]', menu);
  const picked = boxes.filter((box) => box.checked).map((box) => box.dataset.value);
  // 전부 골랐으면 거르지 않는 것과 같다. 필터 표시를 남기지 않는다.
  if (picked.length === boxes.length) delete state.colFilters[column.key];
  else state.colFilters[column.key] = { values: new Set(picked) };
}

function closeColumnMenu() {
  if (state.menu) { state.menu.remove(); state.menu = null; }
}

// ── 조회 조건 저장 ──────────────────────────────────────────────────
//
// 브라우저에 둔다. 서버에 두면 여러 사람이 나눠 쓸 수 있지만 표를 만들고
// 엔드포인트를 늘려야 하고, 실증은 한 사람이 한 자리에서 돌린다. 옮겨야 할
// 때가 오면 아래 두 함수의 저장소만 바꾸면 된다.

const PRESET_KEY = 'padlab-presets';

const loadPresets = () => {
  try { return JSON.parse(localStorage.getItem(PRESET_KEY)) || {}; }
  catch { return {}; }
};
const savePresets = (all) => localStorage.setItem(PRESET_KEY, JSON.stringify(all));

/** 지금 조건을 저장할 수 있는 형태로. Set 은 그대로 직렬화되지 않는다. */
function currentPreset() {
  const filters = {};
  Object.entries(state.colFilters).forEach(([key, rule]) => {
    filters[key] = rule.values ? { values: [...rule.values] } : { min: rule.min, max: rule.max };
  });
  return {
    filters,
    sort: state.sort.map((k) => ({ ...k })),
    since: $('#f-since').value,
    until: $('#f-until').value,
  };
}

async function applyPreset(preset) {
  state.colFilters = {};
  Object.entries(preset.filters || {}).forEach(([key, rule]) => {
    state.colFilters[key] = rule.values
      ? { values: new Set(rule.values) }
      : { min: rule.min ?? null, max: rule.max ?? null };
  });
  state.sort = (preset.sort || []).map((k) => ({ ...k }));

  // 기간이 달라지면 가져올 범위가 달라지므로 다시 받아야 한다.
  const changed = $('#f-since').value !== (preset.since || '')
    || $('#f-until').value !== (preset.until || '');
  $('#f-since').value = preset.since || '';
  $('#f-until').value = preset.until || '';
  if (changed) await loadReadings();
  else drawReadings();
}

function drawPresets(selected = '') {
  const names = Object.keys(loadPresets()).sort((a, b) => a.localeCompare(b, 'ko'));
  $('#f-preset').innerHTML = '<option value="">선택</option>'
    + names.map((name) => `<option value="${escape(name)}" ${name === selected ? 'selected' : ''}>${escape(name)}</option>`).join('');
  $('#f-drop').disabled = !$('#f-preset').value;
}

/** 지금 보이는 그대로 CSV 로 낸다. 화면과 파일이 다르면 어느 쪽이 맞는지 알 수 없다. */
function exportCsv() {
  const rows = visibleRows();
  const line = (cells) => cells.map((cell) => {
    const text = String(cell ?? '');
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  }).join(',');

  const body = [line(COLUMNS.map((c) => c.label))]
    .concat(rows.map((row) => line(COLUMNS.map((column) =>
      (column.kind === 'num' ? raw(column, row) : face(column, row))))))
    .join('\r\n');

  // BOM 을 붙인다. 없으면 엑셀이 한글 머리글을 깨뜨린다.
  const blob = new Blob(['﻿' + body], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'readings.csv';
  link.click();
  URL.revokeObjectURL(url);
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
  // 목록은 파일에서 바로 만든다. 파일명 파싱은 값을 미리 채워 주는 수단일
  // 뿐이라, 규칙을 안 지켰거나 파싱이 실패해도 목록은 그대로 나와야 한다.
  state.uploads = files.map((file) => ({
    filename: file.name, file, target_id: '', date: '', time: '', hint: '',
  }));
  drawUploads();
  if (!files.length) return;

  try {
    const parsed = await api('/api/uploads/parse?kind=capture', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(files.map((f) => f.name)),
    });
    parsed.forEach((row, index) => {
      const slot = state.uploads[index];
      if (!slot || !row.parsed) return;
      slot.target_id = row.known_id ? row.target_id : '';
      if (row.stamp) {
        const at = new Date(row.stamp);
        const pad = (n) => String(n).padStart(2, '0');
        slot.date = `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`;
        slot.time = `${pad(at.getHours())}:${pad(at.getMinutes())}`;
      }
      slot.hint = row.known_id ? '파일명에서' : (row.message || '');
    });
  } catch {
    // 파싱은 편의 기능이다. 실패해도 직접 지정하면 된다.
  }
  drawUploads();
}

function applyToAll() {
  const target = $('#r-all-target').value;
  const date = $('#r-all-date').value;
  const time = $('#r-all-time').value;
  state.uploads.forEach((row) => {
    if (target) row.target_id = target;
    if (date) { row.date = date; row.time = time; }
  });
  drawUploads();
}

function drawUploads() {
  const body = $('#t-uploads tbody');
  body.innerHTML = state.uploads.map((row, index) => {
    const options = state.targets
      .map((t) => `<option value="${escape(t.target_id)}" ${t.target_id === row.target_id ? 'selected' : ''}>${escape(t.target_id)}</option>`)
      .join('');
    return `<tr>
      <td>${escape(row.filename)}</td>
      <td><select data-target="${index}"><option value="">선택</option>${options}</select></td>
      <td><input type="date" data-date="${index}" value="${escape(row.date)}"></td>
      <td><input type="time" data-time="${index}" value="${escape(row.time)}"></td>
      <td class="muted">${escape(row.hint)}</td>
    </tr>`;
  }).join('');

  const on = (attr, field) => $$(`[data-${attr}]`).forEach((node) =>
    node.addEventListener('change', () => {
      state.uploads[Number(node.dataset[attr])][field] = node.value;
      $('#r-go').disabled = !ready();
    }));
  on('target', 'target_id');
  on('date', 'date');
  on('time', 'time');
  $('#r-go').disabled = !ready();
}

// 시:분은 안 채워도 된다. 비우면 그날 00시 00분이다.
const ready = () => state.uploads.length > 0 && state.uploads.every((row) => row.target_id && row.date);

async function startRun() {
  const form = new FormData();
  state.uploads.forEach((row) => form.append('files', row.file, row.filename));
  form.append('target_ids', JSON.stringify(state.uploads.map((r) => r.target_id)));
  form.append('captured_ats', JSON.stringify(
    state.uploads.map((r) => `${r.date}T${r.time || '00:00'}`)));
  form.append('config_override', $('#r-override').value.trim());
  form.append('ignore_baseline_window', String($('#r-ignore-window').checked));

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
    <td>${run.kind === 'rerun'
      ? '<span class="badge info"><i class="dot"></i>재판독</span>'
      : '<span class="badge neutral"><i class="dot"></i>최초</span>'}</td>
    <td>${run.ignore_baseline_window
      ? '<span class="badge warn"><i class="dot"></i>무시</span>'
      : '<span class="badge neutral"><i class="dot"></i>대조</span>'}</td>
    <td><span class="badge ${run.status === 'done' ? 'ok' : run.status === 'failed' ? 'bad' : 'info'}"><i class="dot"></i>${escape(run.status)}</span></td>
    <td class="num">${run.done_captures}/${run.total_captures}</td>
    <td class="num">${run.reading_count}</td>
    <td class="apart">${(run.notes || []).length}</td>
  </tr>`).join('');
}

// ── 기준 사진 이력 ──────────────────────────────────────────────────
//
// 패드를 갈아 붙이면 새 기준이 앞의 것을 대체하고 이력으로 남는다. 어느
// 판독이 어느 기준과 견준 값인지는 부착 일시가 정한다 - 그래서 이력이
// 보이지 않으면 값의 근거를 되짚을 수 없다.

async function loadBaselineHistory() {
  const point = $('#h-point').value;
  const rows = await api(`/api/baselines${point ? `?point_id=${encodeURIComponent(point)}` : ''}`);
  if (!rows.length) {
    $('#h-body').innerHTML = '<div class="card empty">등록된 기준 사진이 없다.</div>';
    return;
  }

  const thumbs = $('#h-thumb').checked;
  const byPoint = {};
  rows.forEach((row) => { (byPoint[row.point_id] ||= []).push(row); });

  $('#h-body').innerHTML = Object.entries(byPoint)
    .sort(([a], [b]) => a.localeCompare(b, 'ko'))
    .map(([pointId, list]) => {
      // 부착 일시 순서가 곧 이력 순서다. 파일명의 회차 표기는 참고값이라
      // 그것으로 줄을 세우지 않는다.
      const ordered = [...list].sort((a, b) => a.effective_from.localeCompare(b.effective_from));
      const info = state.points.find((p) => p.point_id === pointId);
      return `<div class="card">
        <div class="row" style="justify-content:space-between; align-items:center">
          <h3 style="margin:0">${escape(pointId)}
            <span class="muted">${escape(info ? (info.name || '') : '')}</span></h3>
          <span class="badge neutral"><i class="dot"></i>이력 ${ordered.length}건</span>
        </div>
        <div class="scroll"><table>
          <thead><tr>
            <th class="plain">회차</th><th class="plain">상태</th>
            <th class="plain">부착 일시</th><th class="plain">대체된 일시</th>
            <th class="plain">등록 일시</th><th class="plain">원본 파일명</th>
            ${thumbs ? '<th class="plain">사진</th>' : ''}
            <th class="plain actcell"></th>
          </tr></thead>
          <tbody>${ordered.map((row, index) => `<tr>
            <td class="key">${index + 1}</td>
            <td>${row.is_current
              ? '<span class="badge ok"><i class="dot"></i>현행</span>'
              : '<span class="badge neutral"><i class="dot"></i>대체됨</span>'}</td>
            <td>${stamp(row.effective_from)}</td>
            <td>${row.superseded_at ? stamp(row.superseded_at) : '—'}</td>
            <td class="muted">${stamp(row.registered_at)}</td>
            <td class="muted">${escape(row.original_name || '—')}</td>
            ${thumbs ? `<td><a href="/files/${escape(row.file_path)}" target="_blank">
              <img src="/files/${escape(row.file_path)}" loading="lazy"
                   style="height:88px; border-radius:4px; display:block"
                   onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'badge bad',textContent:'파일 없음'}))"></a></td>` : ''}
            <td class="actcell"><span class="acts">
              <button class="ghost tiny" data-base-when="${row.id}">일시 수정</button>
              <button class="ghost tiny" data-base-del="${row.id}">삭제</button>
            </span></td>
          </tr>`).join('')}</tbody>
        </table></div>
      </div>`;
    }).join('');
}

// ── 등록 ────────────────────────────────────────────────────────────

async function loadRegistry() {
  [state.targets, state.points] = await Promise.all([api('/api/targets'), api('/api/points')]);

  const targetOptions = state.targets
    .map((t) => `<option value="${escape(t.target_id)}">${escape(t.target_id)}${t.name ? ` · ${escape(t.name)}` : ''}</option>`).join('');
  const pointOptions = state.points
    .map((p) => `<option value="${escape(p.point_id)}">${escape(p.point_id)}${p.name ? ` · ${escape(p.name)}` : ''}</option>`).join('');

  $('#n-point-target').innerHTML = targetOptions;
  $('#r-all-target').innerHTML = '<option value="">선택</option>' + targetOptions;
  $('#x-point').innerHTML = '<option value="">전체</option>' + pointOptions;
  ['#d-point', '#s-point'].forEach((sel) => { $(sel).innerHTML = '<option value="">선택</option>' + pointOptions; });
  $('#b-point').innerHTML = '<option value="">파일명에서</option>' + pointOptions;
  $('#h-point').innerHTML = '<option value="">전체</option>' + pointOptions;

  const baselines = await api('/api/baselines');
  const byPoint = {};
  baselines.forEach((b) => { (byPoint[b.point_id] ||= []).push(b); });

  const cell = (value) => (value ? escape(value) : '<span class="tnone">—</span>');
  const editing = (kind, id) => state.edit && state.edit.kind === kind && state.edit.id === id;
  const attr = (value) => escape(value ?? '');

  const targetRow = (target) => editing('target', target.target_id)
    ? `<div class="tgrid editing">
        <label class="field">TARGET_ID<input data-f="target_id" value="${attr(target.target_id)}"></label>
        <label class="field">명칭<input data-f="name" value="${attr(target.name)}"></label>
        <label class="field">촬영 위치 설명<input data-f="location_desc" value="${attr(target.location_desc)}"></label>
        <span class="acts">
          <button class="primary tiny" data-save-target="${attr(target.target_id)}">저장</button>
          <button class="secondary tiny" data-cancel>취소</button>
        </span>
      </div>`
    : `<div class="tgrid">
        <span class="tid">${escape(target.target_id)}</span>
        <span class="tname">${cell(target.name)}</span>
        <span class="tdesc">${cell(target.location_desc)}</span>
        <span class="acts">
          <button class="ghost tiny" data-edit-target="${attr(target.target_id)}">수정</button>
          <button class="ghost tiny" data-del-target="${attr(target.target_id)}">삭제</button>
        </span>
      </div>`;

  const targetChoices = (selected) => state.targets
    .map((t) => `<option value="${attr(t.target_id)}" ${t.target_id === selected ? 'selected' : ''}>${escape(t.target_id)}</option>`)
    .join('');

  const pointRow = (point) => {
    const list = byPoint[point.point_id] || [];
    const current = list.find((b) => b.is_current);
    if (editing('point', point.point_id)) {
      return `<tr>
        <td><input data-f="point_id" value="${attr(point.point_id)}"></td>
        <td><input data-f="name" value="${attr(point.name)}"></td>
        <td><input data-f="location_desc" value="${attr(point.location_desc)}"></td>
        <td><select data-f="tone">
          <option value="white" ${point.tone === 'white' ? 'selected' : ''}>white</option>
          <option value="black" ${point.tone === 'black' ? 'selected' : ''}>black</option>
        </select></td>
        <td><select data-f="target_id">${targetChoices(point.target_id)}</select></td>
        <td class="actcell"><span class="acts">
          <button class="primary tiny" data-save-point="${attr(point.point_id)}">저장</button>
          <button class="secondary tiny" data-cancel>취소</button>
        </span></td>
      </tr>`;
    }
    return `<tr>
      <td class="key">${escape(point.point_id)}</td>
      <td>${cell(point.name)}</td>
      <td>${cell(point.location_desc)}</td>
      <td><span class="badge info"><i class="dot"></i>${escape(point.tone)}</span></td>
      <td>${current
        ? `<span class="badge ok"><i class="dot"></i>${stamp(current.effective_from)} 부착</span>`
        : '<span class="badge warn"><i class="dot"></i>없음</span>'}
        ${list.length > 1 ? `<span class="muted">이력 ${list.length}건</span>` : ''}</td>
      <td class="actcell"><span class="acts">
        <button class="ghost tiny" data-edit-point="${attr(point.point_id)}">수정</button>
        <button class="ghost tiny" data-del-point="${attr(point.point_id)}">삭제</button>
      </span></td>
    </tr>`;
  };

  $('#tree').innerHTML = state.targets.map((target) => {
    const children = state.points.filter((p) => p.target_id === target.target_id);
    return `<li>
      ${targetRow(target)}
      <div class="indent">${children.length ? `<table>
        <thead><tr>
          <th class="plain">개소</th><th class="plain">명칭</th>
          <th class="plain">물리적 위치</th><th class="plain">톤</th>
          <th class="plain">기준 사진</th><th class="plain actcell"></th>
        </tr></thead>
        <tbody>${children.map(pointRow).join('')}</tbody>
      </table>` : '<p class="tnone" style="margin:8px 0 0">등록된 개소가 없다</p>'}</div>
    </li>`;
  }).join('') || '<li class="tnone">등록된 촬영 단위가 없다</li>';
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
  $('#f-csv').addEventListener('click', exportCsv);
  $('#f-delete').addEventListener('click', async () => {
    const count = state.selected.size;
    if (!confirm(`판독 결과 ${count}건을 지운다. 되돌릴 수 없다.

원본 사진과 기준 사진은 그대로 두므로 다시 판독할 수 있다.`)) return;
    try {
      const done = await api('/api/readings', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reading_ids: [...state.selected] }),
      });
      state.selected.clear();
      await Promise.all([loadReadings(), loadRuns()]);
      toast(`판독 결과 ${done.deleted}건을 지웠다`);
    } catch (error) { toast(error.message, true); }
  });

  $('#f-preset').addEventListener('change', async () => {
    const name = $('#f-preset').value;
    $('#f-drop').disabled = !name;
    if (!name) return;
    const preset = loadPresets()[name];
    if (!preset) return;
    try { await applyPreset(preset); } catch (error) { toast(error.message, true); }
  });

  $('#f-save').addEventListener('click', () => {
    const name = prompt('이 조회 조건에 붙일 이름', $('#f-preset').value || '');
    if (name === null) return;
    const trimmed = name.trim();
    if (!trimmed) { toast('이름이 비어 있다', true); return; }
    const all = loadPresets();
    if (all[trimmed] && !confirm(`'${trimmed}' 이 이미 있다. 지금 조건으로 덮어쓴다.`)) return;
    all[trimmed] = currentPreset();
    savePresets(all);
    drawPresets(trimmed);
    toast(`'${trimmed}' 으로 저장했다`);
  });

  $('#f-drop').addEventListener('click', () => {
    const name = $('#f-preset').value;
    if (!name || !confirm(`저장된 조회 조건 '${name}' 을 지운다.`)) return;
    const all = loadPresets();
    delete all[name];
    savePresets(all);
    drawPresets();
    toast(`'${name}' 을 지웠다`);
  });

  $('#f-reset').addEventListener('click', () => {
    state.colFilters = {};
    state.sort = [{ key: 'captured_at', desc: true }];
    $('#f-preset').value = '';
    $('#f-drop').disabled = true;
    drawReadings();
  });
  // 메뉴 밖을 누르면 닫는다.
  document.addEventListener('click', closeColumnMenu);
  window.addEventListener('resize', closeColumnMenu);
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

  $('#r-files').addEventListener('change', () => pickFiles().catch((e) => toast(e.message, true)));
  $('#r-apply-all').addEventListener('click', applyToAll);
  $('#r-go').addEventListener('click', startRun);

  $('#d-load').addEventListener('click', () => loadStack().catch((e) => toast(e.message, true)));
  $('#s-load').addEventListener('click', () => loadSeries().catch((e) => toast(e.message, true)));
  $('#x-load').addEventListener('click', () => loadDistribution().catch((e) => toast(e.message, true)));
  $('#h-load').addEventListener('click', () => loadBaselineHistory().catch((e) => toast(e.message, true)));

  // 기준 사진 이력의 수정·삭제. 행이 다시 그려지므로 위임해 받는다.
  document.addEventListener('click', async (event) => {
    const node = event.target.closest?.('[data-base-when],[data-base-del]');
    if (!node) return;
    try {
      if (node.dataset.baseWhen) {
        const when = prompt('부착 일시를 다시 넣는다. 예: 2026-08-20 또는 2026-08-20T09:30');
        if (when === null) return;
        const text = when.trim();
        if (!text) { toast('일시가 비어 있다', true); return; }
        await api(`/api/baselines/${node.dataset.baseWhen}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ effective_from: text.includes('T') ? text : `${text}T00:00` }),
        });
        toast('부착 일시를 고쳤다');
      } else {
        if (!confirm('이 기준 사진을 지운다. 이 기준으로 나온 판독이 남아 있으면 지워지지 않는다.')) return;
        await api(`/api/baselines/${node.dataset.baseDel}`, { method: 'DELETE' });
        toast('기준 사진을 지웠다');
      }
      await Promise.all([loadRegistry(), loadBaselineHistory()]);
    } catch (error) { toast(error.message, true); }
  });
  $('#h-point').addEventListener('change', () => loadBaselineHistory().catch((e) => toast(e.message, true)));
  $('#h-thumb').addEventListener('change', () => loadBaselineHistory().catch((e) => toast(e.message, true)));

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

  // 등록 화면의 수정·삭제. 행이 다시 그려지므로 개별 버튼에 붙이지 않고
  // 한 곳에서 위임해 받는다.
  document.addEventListener('click', async (event) => {
    const node = event.target.closest?.('[data-edit-target],[data-edit-point],[data-save-target],[data-save-point],[data-del-target],[data-del-point],[data-cancel]');
    if (!node) return;
    const data = node.dataset;

    if (data.cancel !== undefined) { state.edit = null; await loadRegistry(); return; }
    if (data.editTarget) { state.edit = { kind: 'target', id: data.editTarget }; await loadRegistry(); return; }
    if (data.editPoint) { state.edit = { kind: 'point', id: data.editPoint }; await loadRegistry(); return; }

    try {
      if (data.saveTarget) {
        await api(`/api/targets/${encodeURIComponent(data.saveTarget)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(fields(node)),
        });
        toast('촬영 단위를 고쳤다');
      } else if (data.savePoint) {
        await api(`/api/points/${encodeURIComponent(data.savePoint)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(fields(node)),
        });
        toast('개소를 고쳤다');
      } else if (data.delTarget) {
        if (!confirm(`촬영 단위 ${data.delTarget} 를 지운다. 되돌릴 수 없다.`)) return;
        await api(`/api/targets/${encodeURIComponent(data.delTarget)}`, { method: 'DELETE' });
        toast('촬영 단위를 지웠다');
      } else if (data.delPoint) {
        if (!confirm(`개소 ${data.delPoint} 를 지운다. 이 개소의 기준 사진도 함께 사라진다.`)) return;
        await api(`/api/points/${encodeURIComponent(data.delPoint)}`, { method: 'DELETE' });
        toast('개소를 지웠다');
      }
      state.edit = null;
      await loadRegistry();
    } catch (error) {
      toast(error.message, true);
    }
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
    // 시:분을 비우면 그날 00시 00분이다. 부착은 대개 날짜 단위로 기억하고,
    // 같은 날 두 번 갈아 붙이는 일은 거의 없다.
    const date = $('#b-date').value;
    if (date) form.append('effective_from', `${date}T${$('#b-time').value || '00:00'}`);
    try {
      await api('/api/baselines', { method: 'POST', body: form });
      $('#b-file').value = $('#b-date').value = $('#b-time').value = '';
      await loadRegistry();
      await loadBaselineHistory();
      toast('기준 사진을 등록했다');
    } catch (error) { toast(error.message, true); }
  });
}

/** 편집 중인 행의 입력값을 모은다. 빈 칸은 null 로 보내 값을 지운다. */
function fields(node) {
  const scope = node.closest('tr') || node.closest('.tgrid');
  const out = {};
  $$('[data-f]', scope).forEach((input) => {
    const value = input.value.trim();
    out[input.dataset.f] = value === '' ? null : value;
  });
  return out;
}

async function boot() {
  // 기본은 라이트다. 디자인 시스템의 기본값은 다크지만 이 화면은 사무실
  // 주간 사용이라 라이트로 연다. 고른 값은 브라우저에 남는다.
  const saved = localStorage.getItem('padlab-theme');
  document.documentElement.dataset.theme = saved || 'light';
  $('#theme').textContent = document.documentElement.dataset.theme === 'dark' ? '라이트' : '다크';

  bind();
  route();
  drawPresets();
  await loadRegistry();
  await Promise.all([loadReadings(), loadRuns()]);
}

boot().catch((error) => toast(error.message, true));
