/*
 * WarAsset — sidlogik. Vanlig JS mot Fas 1:s /api/-endpoints, ingen
 * frontend-ramverk. Databasen (via API:t) är källan till sanning — ingen
 * localStorage längre (till skillnad från Miniatyrarkiv.dc.html-mockupen).
 *
 * Fullständig omrendering (render()/renderDialog()) körs bara vid
 * strukturella ändringar (öppna/stänga dialogen, byta läge, ny
 * sökträff/urval). Textinmatning (namn/antal/poäng) uppdaterar state och
 * DOM riktat, utan att bygga om inputen — annars tappar fältet fokus/
 * markörposition på varje tangenttryckning.
 */
(() => {
  'use strict';

  const SYSTEM_LABELS = { '40k': '40k', kill_team: 'Kill Team', aos: 'AoS' };
  const STATUS_LABEL = { unbuilt: 'Ej byggd', built: 'Byggd', painted: 'Målad' };
  const STATUS_ORDER = { unbuilt: 0, built: 1, painted: 2 };
  const CUSTOM_GROUP_KEY = '__custom__';

  const state = {
    units: [],
    search: '',
    filterSystem: 'all',
    filterRole: 'all',
    view: 'grid',
    sortKey: 'name',
    collapsed: {},
    dialog: null,
    viewingUnitId: null,
  };

  // ---------------------------------------------------------------------
  // API + små hjälpare
  // ---------------------------------------------------------------------

  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (res.status === 204) return null;
    let body = null;
    try { body = await res.json(); } catch (e) { /* icke-JSON-svar */ }
    if (!res.ok) throw new Error((body && body.error) || ('HTTP ' + res.status));
    return body;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function pointsForCount(pointsTable, count) {
    if (!pointsTable || !pointsTable.length) return null;
    const exact = pointsTable.find((r) => r.count === count);
    if (exact) return exact.points;
    let closest = pointsTable[0];
    let bestDiff = Math.abs((closest.count || 0) - count);
    for (const row of pointsTable) {
      const diff = Math.abs((row.count || 0) - count);
      if (diff < bestDiff) { closest = row; bestDiff = diff; }
    }
    return closest.points;
  }

  async function loadUnits() {
    state.units = await api('/api/units');
    render();
  }

  // ---------------------------------------------------------------------
  // Gruppering/filtrering/sortering — motsvarar mockupens renderVals(),
  // men grupperar per catalogue_name (BSData-fraktion) istället för den
  // fritextade "army" mockupen hade, och saknar en fast ARMY_ORDER-lista
  // (fraktionerna kommer dynamiskt från BSData-synken, inte en fast seed).
  // Enheter utan entry_id (anpassade enheter, se produktbeslutet i
  // fas2-warasset-ui.md) har ingen fraktion och grupperas för sig.
  // ---------------------------------------------------------------------

  function groupKeyFor(u) { return u.catalogue_name || CUSTOM_GROUP_KEY; }
  function groupLabelFor(u) { return u.catalogue_name || 'Anpassade enheter'; }
  function groupSystemLabel(u) { return u.system_key ? (SYSTEM_LABELS[u.system_key] || u.system_key) : 'Anpassad'; }

  function computeView() {
    const search = state.search.trim().toLowerCase();
    const filtered = state.units.filter((u) => {
      if (search && !u.name.toLowerCase().includes(search)) return false;
      if (state.filterSystem !== 'all' && u.system_key !== state.filterSystem) return false;
      if (state.filterRole !== 'all' && (u.role || 'Övrigt') !== state.filterRole) return false;
      return true;
    });

    const groupsMap = new Map();
    for (const u of filtered) {
      const key = groupKeyFor(u);
      if (!groupsMap.has(key)) groupsMap.set(key, []);
      groupsMap.get(key).push(u);
    }

    const sortFn = (a, b) => {
      if (state.sortKey === 'points') return (b.computed_points || 0) - (a.computed_points || 0);
      if (state.sortKey === 'count') return b.count - a.count;
      if (state.sortKey === 'status') return STATUS_ORDER[a.status] - STATUS_ORDER[b.status];
      return a.name.localeCompare(b.name, 'sv');
    };

    const groupKeys = Array.from(groupsMap.keys()).sort((a, b) => {
      if (a === CUSTOM_GROUP_KEY) return 1;
      if (b === CUSTOM_GROUP_KEY) return -1;
      return a.localeCompare(b, 'sv');
    });

    let visibleCount = 0;
    const groups = groupKeys.map((key) => {
      const groupUnits = groupsMap.get(key).slice().sort(sortFn);
      visibleCount += groupUnits.length;
      const models = groupUnits.reduce((sum, u) => sum + u.count, 0);
      const points = groupUnits.reduce((sum, u) => sum + (u.computed_points || 0), 0);
      const sample = groupUnits[0];
      return {
        key,
        name: groupLabelFor(sample),
        systemLabel: groupSystemLabel(sample),
        count: groupUnits.length,
        models,
        points,
        units: groupUnits,
      };
    });

    return { groups, visibleCount };
  }

  // ---------------------------------------------------------------------
  // Rendering av huvudvyn
  // ---------------------------------------------------------------------

  function statusTagClass(status) {
    if (status === 'painted') return 'tag tag-accent status-tag';
    if (status === 'built') return 'tag tag-outline status-tag';
    return 'tag tag-neutral status-tag';
  }

  function unitCardHtml(u) {
    const photo = u.photo_path
      ? `<div class="unit-photo lighten"><img src="${escapeHtml(u.photo_path)}" alt=""></div>`
      : `<div class="unit-photo"><span class="unit-photo-label">FOTO: ${escapeHtml(u.name)}</span></div>`;
    const pointsLabel = u.computed_points == null ? '–' : (u.computed_points + ' p');
    return `
      <div class="unit-card card elev-sm">
        ${photo}
        <div class="unit-card-body">
          <div class="unit-card-top">
            <div class="card-kicker">${escapeHtml(u.catalogue_name || 'Anpassad')}</div>
            <div class="tag tag-neutral">${escapeHtml(u.role || 'Övrigt')}</div>
          </div>
          <button type="button" class="unit-card-name name-link" data-action="show-stats" data-unit-id="${u.id}">${escapeHtml(u.name)}</button>
          <div class="unit-card-meta">
            <span>${u.count} mod.</span>
            <span>${pointsLabel}</span>
          </div>
          <div class="unit-card-foot">
            <span class="${statusTagClass(u.status)}">${STATUS_LABEL[u.status]}</span>
            <div class="unit-card-actions">
              <button type="button" class="btn btn-ghost" data-action="edit" data-unit-id="${u.id}">Redigera</button>
              <button type="button" class="btn btn-ghost" data-action="delete" data-unit-id="${u.id}">Ta bort</button>
            </div>
          </div>
        </div>
      </div>`;
  }

  function unitRowHtml(u) {
    const pointsLabel = u.computed_points == null ? '–' : (u.computed_points + ' p');
    return `
      <tr>
        <td><button type="button" class="name-link" data-action="show-stats" data-unit-id="${u.id}">${escapeHtml(u.name)}</button> <span class="name-sub">· ${escapeHtml(u.role || 'Övrigt')}</span></td>
        <td class="num">${u.count}</td>
        <td class="num">${pointsLabel}</td>
        <td class="center"><span class="${statusTagClass(u.status)}">${STATUS_LABEL[u.status]}</span></td>
        <td class="actions">
          <button type="button" class="btn btn-ghost" data-action="edit" data-unit-id="${u.id}">Redigera</button>
          <button type="button" class="btn btn-ghost" data-action="delete" data-unit-id="${u.id}">Ta bort</button>
        </td>
      </tr>`;
  }

  function groupHtml(group) {
    const expanded = !state.collapsed[group.key];
    let body = '';
    if (expanded) {
      if (state.view === 'grid') {
        body = `<div class="unit-grid">${group.units.map(unitCardHtml).join('')}</div>`;
      } else {
        body = `<div class="unit-table-wrap"><table class="table unit-table">
          <thead><tr><th>Enhet</th><th style="text-align:right">Antal</th><th style="text-align:right">Poäng</th><th style="text-align:center">Status</th><th></th></tr></thead>
          <tbody>${group.units.map(unitRowHtml).join('')}</tbody>
        </table></div>`;
      }
    }
    return `
      <div class="unit-group">
        <button type="button" class="group-header" data-action="toggle-group" data-group-key="${escapeHtml(group.key)}">
          <span class="group-chevron ${expanded ? 'is-expanded' : ''}">▶</span>
          <h3 class="group-title">${escapeHtml(group.name)}</h3>
          <span class="tag tag-neutral">${escapeHtml(group.systemLabel)}</span>
          <span class="group-meta">${group.count} enheter · ${group.models} modeller · ${group.points} p</span>
        </button>
        ${expanded ? `<div>${body}</div>` : ''}
      </div>`;
  }

  function renderStats() {
    const totalUnits = state.units.length;
    const totalModels = state.units.reduce((s, u) => s + u.count, 0);
    const totalPoints = state.units.reduce((s, u) => s + (u.computed_points || 0), 0);
    const paintedCount = state.units.filter((u) => u.status === 'painted').length;
    const paintedPct = totalUnits ? Math.round((paintedCount / totalUnits) * 100) : 0;
    document.getElementById('stat-total-units').textContent = totalUnits;
    document.getElementById('stat-total-models').textContent = totalModels;
    document.getElementById('stat-total-points').textContent = totalPoints;
    document.getElementById('stat-painted-pct').textContent = paintedPct;
    document.getElementById('stat-bar-fill').style.width = paintedPct + '%';
  }

  function renderRoleOptions() {
    const roles = Array.from(new Set(state.units.map((u) => u.role || 'Övrigt'))).sort((a, b) => a.localeCompare(b, 'sv'));
    const sel = document.getElementById('role-select');
    const current = state.filterRole;
    sel.innerHTML = '<option value="all">Typ: Alla</option>' + roles.map((r) => `<option value="${escapeHtml(r)}">Typ: ${escapeHtml(r)}</option>`).join('');
    sel.value = roles.includes(current) ? current : 'all';
    state.filterRole = sel.value;
  }

  function render() {
    closeViewDialog();
    renderStats();
    renderRoleOptions();

    const { groups, visibleCount } = computeView();
    document.getElementById('visible-hint').textContent = visibleCount + ' av ' + state.units.length + ' enheter visas';

    const container = document.getElementById('groups-container');
    const empty = document.getElementById('empty-state');
    if (groups.length === 0) {
      container.innerHTML = '';
      empty.hidden = false;
    } else {
      empty.hidden = true;
      container.innerHTML = groups.map(groupHtml).join('');
    }
  }

  // ---------------------------------------------------------------------
  // Enhetsdetalj / datasheet-vy (Fas 3) — visas vid klick på ett enhetsnamn.
  // Importerad från designcanvasen Miniatyrarkiv.dc.html ("Datasheet view
  // dialog"): en fullstor modal (samma dialog-backdrop-mönster som add/
  // edit-dialogen), inte en liten positionerad popover som det första
  // utkastet. Mockupens layout var hårdkodad för 40k (fasta
  // M/T/SV/W/LD/OC- och Range/A/BS/S/AP/D/Keywords-kolumner, byggda från
  // manuellt författad SEED-data) — här byggs kolumnerna istället
  // DYNAMISKT från entry.profiles (se viewDialogBodyHtml/
  // viewWeaponsTableHtml nedan), eftersom Kill Team/AoS har andra
  // karaktäristik-set (se CLAUDE.md, Fas 3).
  // ---------------------------------------------------------------------

  const VIEW_HEADER_TYPE_RE = /^(unit|operative|model)$/i;

  // BSData:s XML listar en profils <characteristic>-element ALFABETISKT
  // (verifierat: en 40k-vapenprofil kommer ur bsdata_sync som
  // A/AP/D/Keywords/Range/S/WS, inte spelets naturliga läsordning) — den
  // ordningen ärvs rakt av i entries.profiles. Den här listan är bara en
  // visuell prioritering för vanliga förkortningar över alla tre
  // spelsystemen (se CLAUDE.md, Fas 3) så en datasheet läses i naturlig
  // ordning (M/T/SV/W/... , Range/A/BS/S/AP/D/Keywords); allt som inte
  // finns med hamnar sist, alfabetiskt — påverkar bara VISNINGSORDNING,
  // inte vilken data som samlas in.
  const CHAR_ORDER_PRIORITY = [
    'M', 'T', 'SV', 'Sv', 'W', 'LD', 'Ld', 'OC', 'APL', 'GA', 'DF', 'Max',
    'Range', 'A', 'WS', 'BS', 'S', 'AP', 'D', 'Type', 'SR',
    'Keywords', 'Abilities', 'Description', 'Effect',
  ];

  function sortedCharKeys(characteristics) {
    return Object.keys(characteristics || {}).sort((a, b) => {
      const ia = CHAR_ORDER_PRIORITY.indexOf(a);
      const ib = CHAR_ORDER_PRIORITY.indexOf(b);
      if (ia === -1 && ib === -1) return a.localeCompare(b);
      if (ia === -1) return 1;
      if (ib === -1) return -1;
      return ia - ib;
    });
  }

  function closeViewDialog() {
    state.viewingUnitId = null;
    document.getElementById('view-dialog-backdrop').hidden = true;
  }

  function viewStatLineHtml(headerProfile) {
    if (!headerProfile) return '';
    const chars = headerProfile.characteristics || {};
    const boxes = sortedCharKeys(chars).map((k) => [k, chars[k]]).map(([k, v]) => `
      <div class="view-stat-box">
        <span class="view-stat-label">${escapeHtml(k)}</span>
        <span class="view-stat-value">${escapeHtml(v)}</span>
      </div>`).join('');
    return boxes ? `<div class="view-stat-line">${boxes}</div>` : '';
  }

  function viewAbilityHtml(p) {
    const chars = p.characteristics || {};
    const keys = sortedCharKeys(chars);
    // Vanligast: EN karaktäristik som håller en text (Description/Ability/
    // Effect m.fl. beroende på spelsystem, se CLAUDE.md) — visas som ett
    // stycke, precis som mockupens ab.desc. Ovanliga profiler med flera
    // karaktäristiker faller tillbaka på samma chip-grid som tidigare.
    const body = keys.length === 1
      ? `<p class="view-ability-desc">${escapeHtml(chars[keys[0]])}</p>`
      : `<div class="stats-characteristics">${keys.map((k) => `
          <div class="stat-chip">
            <div class="stat-chip-label">${escapeHtml(k)}</div>
            <div class="stat-chip-value">${escapeHtml(chars[k])}</div>
          </div>`).join('')}</div>`;
    return `
      <div class="view-ability">
        <div class="view-ability-head">
          <span class="view-ability-name">${escapeHtml(p.name || '')}</span>
          <span class="tag tag-neutral">${escapeHtml(p.type || '')}</span>
        </div>
        ${body}
      </div>`;
  }

  function viewWeaponsTableHtml(heading, weapons) {
    if (!weapons.length) return '';
    const keySet = new Set();
    weapons.forEach((w) => Object.keys(w.characteristics || {}).forEach((k) => keySet.add(k)));
    const keys = sortedCharKeys(Object.fromEntries(Array.from(keySet, (k) => [k, true])));
    const thead = '<tr><th>Namn</th>' + keys.map((k) => `<th>${escapeHtml(k)}</th>`).join('') + '</tr>';
    const rows = weapons.map((w) => {
      const cells = keys.map((k) => `<td>${escapeHtml((w.characteristics && w.characteristics[k]) ?? '–')}</td>`).join('');
      return `<tr><td>${escapeHtml(w.name || '')}</td>${cells}</tr>`;
    }).join('');
    return `
      <div class="view-weapons-section">
        <div class="view-weapons-heading">${escapeHtml(heading)}</div>
        <div class="view-weapons-table-wrap">
          <table class="view-weapons-table"><thead>${thead}</thead><tbody>${rows}</tbody></table>
        </div>
      </div>`;
  }

  function viewDialogBodyHtml(entry) {
    const profiles = entry.profiles || [];
    if (!profiles.length) {
      return '<p class="view-nolink">Ingen profildata tillgänglig i BSData för den här posten.</p>';
    }
    const header = profiles.find((p) => VIEW_HEADER_TYPE_RE.test(p.type || '')) || profiles[0];
    const rest = profiles.filter((p) => p !== header);
    const ranged = rest.filter((p) => /ranged/i.test(p.type || ''));
    const melee = rest.filter((p) => /melee/i.test(p.type || ''));
    const otherWeapons = rest.filter((p) => /weapon/i.test(p.type || '') && !ranged.includes(p) && !melee.includes(p));
    const abilities = rest.filter((p) => !ranged.includes(p) && !melee.includes(p) && !otherWeapons.includes(p));

    return viewStatLineHtml(header) +
      abilities.map(viewAbilityHtml).join('') +
      viewWeaponsTableHtml('Ranged Weapons', ranged) +
      viewWeaponsTableHtml('Melee Weapons', melee) +
      viewWeaponsTableHtml('Vapen', otherWeapons);
  }

  function openViewDialog(unitId) {
    const u = state.units.find((x) => x.id === unitId);
    if (!u) return;
    state.viewingUnitId = unitId;
    document.getElementById('view-dialog-backdrop').hidden = false;
    document.getElementById('view-dialog-name').textContent = u.name;
    document.getElementById('view-dialog-keywords').textContent =
      [u.catalogue_name, u.role].filter(Boolean).join(' · ') || 'Anpassad enhet';

    const body = document.getElementById('view-dialog-body');
    if (u.entry_id == null) {
      body.innerHTML = '<p class="view-nolink">Ingen BSData-koppling — anpassad enhet.</p>';
      return;
    }
    body.innerHTML = '<p class="field-hint">Laddar…</p>';
    api('/api/entries/' + u.entry_id).then((entry) => {
      if (state.viewingUnitId !== unitId) return; // stängd/bytt under tiden
      body.innerHTML = viewDialogBodyHtml(entry);
    }).catch((e) => {
      if (state.viewingUnitId !== unitId) return;
      body.innerHTML = `<p class="view-nolink">Kunde inte hämta statistik: ${escapeHtml(e.message)}</p>`;
    });
  }

  function initViewDialog() {
    const backdrop = document.getElementById('view-dialog-backdrop');
    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) closeViewDialog(); });
    document.getElementById('view-dialog-close').addEventListener('click', closeViewDialog);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !backdrop.hidden) closeViewDialog();
    });
  }

  // ---------------------------------------------------------------------
  // Add/Edit-dialogen
  // ---------------------------------------------------------------------

  let searchDebounceTimer = null;

  function openAddDialog() {
    state.dialog = {
      open: true,
      mode: 'search',
      editingId: null,
      entryId: null,
      system: state.filterSystem !== 'all' ? state.filterSystem : '40k',
      nameQuery: '',
      searchResults: [],
      searchLoading: false,
      selectedEntry: null,
      count: 5,
      status: 'unbuilt',
      photoPath: null,
      customName: '',
      customPoints: '',
      saving: false,
      error: null,
    };
    renderDialog();
  }

  async function openEditDialog(unitId) {
    const u = state.units.find((x) => x.id === unitId);
    if (!u) return;
    const isCustom = u.entry_id == null;
    state.dialog = {
      open: true,
      mode: isCustom ? 'custom' : 'search',
      editingId: u.id,
      entryId: u.entry_id,
      system: u.system_key || '40k',
      nameQuery: u.name,
      searchResults: [],
      searchLoading: false,
      selectedEntry: null,
      count: u.count,
      status: u.status,
      photoPath: u.photo_path,
      customName: u.name_override || u.name || '',
      customPoints: u.points_override != null ? String(u.points_override) : '',
      saving: false,
      error: null,
    };
    renderDialog();
    if (!isCustom) {
      try {
        const entry = await api('/api/entries/' + u.entry_id);
        if (!state.dialog || state.dialog.editingId !== unitId) return; // dialogen stängdes/byttes under tiden
        state.dialog.selectedEntry = entry;
        updateSelectedEntryBox();
        updateComputedPoints();
      } catch (e) {
        if (state.dialog) { state.dialog.error = 'Kunde inte hämta BSData-posten: ' + e.message; renderDialogError(); }
      }
    }
  }

  function closeDialog() {
    state.dialog = null;
    document.getElementById('dialog-backdrop').hidden = true;
  }

  function renderDialogError() {
    const el = document.getElementById('dialog-error');
    if (state.dialog && state.dialog.error) { el.textContent = state.dialog.error; el.hidden = false; }
    else { el.hidden = true; el.textContent = ''; }
  }

  function fieldSegHtml(name, options, current) {
    return `<div class="seg" data-seg="${name}">` + options.map(([value, label]) =>
      `<label class="seg-opt"><input type="radio" name="${name}" value="${value}" ${value === current ? 'checked' : ''}> ${label}</label>`
    ).join('') + '</div>';
  }

  function selectedEntryBoxHtml() {
    const e = state.dialog.selectedEntry;
    if (!e) return '';
    return `
      <div class="selected-entry" id="selected-entry-box">
        <div class="selected-entry-name">${escapeHtml(e.name)}</div>
        <div class="selected-entry-meta">${escapeHtml(e.catalogue_name)} · ${escapeHtml(e.role || 'Övrigt')}</div>
      </div>`;
  }

  function computedPointsText() {
    const d = state.dialog;
    if (!d.selectedEntry) return '–';
    const count = parseInt(d.count, 10);
    const pts = pointsForCount(d.selectedEntry.points_table, Number.isFinite(count) ? count : 0);
    return pts == null ? '–' : (pts + ' p');
  }

  function photoRowHtml() {
    const d = state.dialog;
    if (!d.editingId) return '';
    const photo = d.photoPath
      ? `<div class="unit-photo lighten"><img src="${escapeHtml(d.photoPath)}" alt=""></div>`
      : `<div class="unit-photo"><span class="unit-photo-label">Inget foto</span></div>`;
    return `
      <div class="field">
        <label>Foto</label>
        <div class="photo-row">
          ${photo}
          <input type="file" id="photo-input" accept="image/jpeg,image/png,image/webp,image/gif">
        </div>
      </div>`;
  }

  function dialogFieldsHtml() {
    const d = state.dialog;
    if (d.mode === 'search') {
      return `
        <div class="field">
          <label>Spelsystem</label>
          ${fieldSegHtml('draft-system', [['40k', '40k'], ['kill_team', 'Kill Team'], ['aos', 'AoS']], d.system)}
        </div>
        <div class="field combobox">
          <label>Namn</label>
          <input class="input" type="text" id="name-search-input" autocomplete="off" placeholder="Sök t.ex. Plague Marines…" value="${escapeHtml(d.nameQuery)}">
          <div class="combobox-results" id="combobox-results" hidden></div>
        </div>
        <div id="selected-entry-slot">${selectedEntryBoxHtml()}</div>
        <div class="field-row">
          <div class="field">
            <label>Antal modeller</label>
            <input class="input" type="number" min="1" id="count-input" value="${escapeHtml(d.count)}">
          </div>
          <div class="field">
            <label>Poäng</label>
            <div class="readonly-value" id="points-display">${computedPointsText()}</div>
          </div>
        </div>
        <div class="field">
          <label>Målningsstatus</label>
          ${fieldSegHtml('draft-status', [['unbuilt', 'Ej byggd'], ['built', 'Byggd'], ['painted', 'Målad']], d.status)}
        </div>
        ${photoRowHtml()}
      `;
    }
    return `
      <div class="field">
        <label>Namn</label>
        <input class="input" type="text" id="custom-name-input" value="${escapeHtml(d.customName)}" placeholder="t.ex. Min konverterade Typhus">
      </div>
      <div class="field-row">
        <div class="field">
          <label>Antal modeller</label>
          <input class="input" type="number" min="1" id="count-input" value="${escapeHtml(d.count)}">
        </div>
        <div class="field">
          <label>Poäng (valfritt)</label>
          <input class="input" type="number" min="0" id="custom-points-input" value="${escapeHtml(d.customPoints)}" placeholder="–">
        </div>
      </div>
      <div class="field">
        <label>Målningsstatus</label>
        ${fieldSegHtml('draft-status', [['unbuilt', 'Ej byggd'], ['built', 'Byggd'], ['painted', 'Målad']], d.status)}
      </div>
      ${photoRowHtml()}
      <p class="field-hint">Anpassad enhet: finns inte i BSData-katalogen (t.ex. en konvertering/scratch-build), så fraktion/roll fylls inte i automatiskt.</p>
    `;
  }

  function renderDialog() {
    const d = state.dialog;
    document.getElementById('dialog-backdrop').hidden = false;
    document.getElementById('dialog-title').textContent = d.editingId ? 'Redigera enhet' : 'Ny enhet';
    document.getElementById('dialog-fields').innerHTML = dialogFieldsHtml();
    document.getElementById('dialog-mode-toggle').innerHTML = d.mode === 'search'
      ? 'Hittar du inte enheten i BSData? <a data-action="switch-mode" data-mode="custom">Lägg till en anpassad enhet</a>'
      : '<a data-action="switch-mode" data-mode="search">← Sök i BSData istället</a>';
    document.getElementById('dialog-save').disabled = !!d.saving;
    renderDialogError();
  }

  function updateSelectedEntryBox() {
    const slot = document.getElementById('selected-entry-slot');
    if (slot) slot.innerHTML = selectedEntryBoxHtml();
  }

  function updateComputedPoints() {
    const el = document.getElementById('points-display');
    if (el) el.textContent = computedPointsText();
  }

  function updateComboboxDropdown() {
    const d = state.dialog;
    const box = document.getElementById('combobox-results');
    if (!box) return;
    if (d.searchLoading) {
      box.innerHTML = '<div class="combobox-empty">Söker…</div>';
      box.hidden = false;
      return;
    }
    if (!d.nameQuery.trim()) { box.hidden = true; box.innerHTML = ''; return; }
    if (d.searchResults.length === 0) {
      box.innerHTML = '<div class="combobox-empty">Inga träffar.</div>';
      box.hidden = false;
      return;
    }
    box.innerHTML = d.searchResults.map((r) => `
      <div class="combobox-result" data-action="select-entry" data-entry-id="${r.id}">
        <div class="combobox-result-name">${escapeHtml(r.name)}</div>
        <div class="combobox-result-meta">${escapeHtml(r.catalogue_name)} · ${escapeHtml(r.role || 'Övrigt')}</div>
      </div>`).join('');
    box.hidden = false;
  }

  function runSearch() {
    const d = state.dialog;
    clearTimeout(searchDebounceTimer);
    const q = d.nameQuery.trim();
    if (!q) { d.searchResults = []; d.searchLoading = false; updateComboboxDropdown(); return; }
    searchDebounceTimer = setTimeout(async () => {
      d.searchLoading = true;
      updateComboboxDropdown();
      try {
        const results = await api(`/api/entries/search?system=${encodeURIComponent(d.system)}&q=${encodeURIComponent(q)}`);
        if (state.dialog !== d) return;
        d.searchResults = results;
      } catch (e) {
        if (state.dialog !== d) return;
        d.searchResults = [];
      }
      d.searchLoading = false;
      updateComboboxDropdown();
    }, 250);
  }

  function selectEntry(entryId) {
    const d = state.dialog;
    const entry = d.searchResults.find((r) => r.id === entryId);
    if (!entry) return;
    d.selectedEntry = entry;
    d.entryId = entry.id;
    d.nameQuery = entry.name;
    d.searchResults = [];
    const input = document.getElementById('name-search-input');
    if (input) input.value = entry.name;
    updateSelectedEntryBox();
    updateComputedPoints();
    const box = document.getElementById('combobox-results');
    if (box) { box.hidden = true; box.innerHTML = ''; }
  }

  function clearSelection() {
    const d = state.dialog;
    d.selectedEntry = null;
    d.entryId = null;
    updateSelectedEntryBox();
    updateComputedPoints();
  }

  async function uploadPhoto(file) {
    const d = state.dialog;
    if (!d || !d.editingId || !file) return;
    const formData = new FormData();
    formData.append('photo', file);
    try {
      const updated = await api('/api/units/' + d.editingId + '/photo', { method: 'POST', body: formData });
      d.photoPath = updated.photo_path;
      const u = state.units.find((x) => x.id === d.editingId);
      if (u) u.photo_path = updated.photo_path;
      renderDialog();
    } catch (e) {
      d.error = 'Foto kunde inte laddas upp: ' + e.message;
      renderDialogError();
    }
  }

  async function saveDialog() {
    const d = state.dialog;
    d.error = null;
    let payload;

    const count = parseInt(d.count, 10);
    if (!count || count < 1) { d.error = 'Antal måste vara ett positivt heltal.'; renderDialogError(); return; }

    if (d.mode === 'search') {
      if (!d.entryId) { d.error = 'Välj en enhet ur sökresultaten.'; renderDialogError(); return; }
      payload = { entry_id: d.entryId, name_override: null, count, status: d.status, points_override: null };
    } else {
      const name = d.customName.trim();
      if (!name) { d.error = 'Namn krävs.'; renderDialogError(); return; }
      let pointsOverride = null;
      if (d.customPoints !== '' && d.customPoints != null) {
        pointsOverride = parseInt(d.customPoints, 10);
        if (Number.isNaN(pointsOverride)) { d.error = 'Poäng måste vara ett heltal.'; renderDialogError(); return; }
      }
      payload = { entry_id: null, name_override: name, count, status: d.status, points_override: pointsOverride };
    }

    d.saving = true;
    document.getElementById('dialog-save').disabled = true;
    try {
      if (d.editingId) {
        await api('/api/units/' + d.editingId, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      } else {
        await api('/api/units', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      }
      closeDialog();
      await loadUnits();
    } catch (e) {
      d.saving = false;
      d.error = e.message;
      renderDialogError();
      document.getElementById('dialog-save').disabled = false;
    }
  }

  async function deleteUnit(unitId) {
    const u = state.units.find((x) => x.id === unitId);
    if (!u) return;
    if (!window.confirm('Ta bort "' + u.name + '"?')) return;
    try {
      await api('/api/units/' + unitId, { method: 'DELETE' });
      await loadUnits();
    } catch (e) {
      alert('Kunde inte ta bort enheten: ' + e.message);
    }
  }

  // ---------------------------------------------------------------------
  // "Synka BSData nu" — pollar /api/game-systems tills last_synced_at
  // ändrats för alla tre system, se fas2-warasset-ui.md uppgift 4.
  // ---------------------------------------------------------------------

  async function triggerSync() {
    const btn = document.getElementById('sync-btn');
    const status = document.getElementById('sync-status');
    status.classList.remove('is-error');
    try {
      const before = await api('/api/game-systems');
      const beforeMap = new Map(before.map((g) => [g.key, g.last_synced_at]));
      const res = await fetch('/api/sync', { method: 'POST' });
      if (res.status === 409) { status.textContent = 'En synk körs redan…'; return; }
      if (!res.ok) throw new Error('HTTP ' + res.status);
      btn.disabled = true;
      status.textContent = 'Synkar BSData…';

      const deadline = Date.now() + 2 * 60 * 1000;
      const poll = async () => {
        if (Date.now() > deadline) {
          status.textContent = 'Synken pågår fortfarande i bakgrunden (kan ta ett tag vid en första klon).';
          btn.disabled = false;
          return;
        }
        const now = await api('/api/game-systems');
        const done = now.every((g) => g.last_synced_at !== beforeMap.get(g.key));
        if (done) {
          status.textContent = 'Synk klar.';
          btn.disabled = false;
          await loadUnits();
          return;
        }
        setTimeout(poll, 3000);
      };
      setTimeout(poll, 3000);
    } catch (e) {
      status.classList.add('is-error');
      status.textContent = 'Synk misslyckades: ' + e.message;
      btn.disabled = false;
    }
  }

  // ---------------------------------------------------------------------
  // Händelsebindning (delegerad där innehållet byggs om, direkt annars)
  // ---------------------------------------------------------------------

  function initNav() {
    document.getElementById('search-input').addEventListener('input', (e) => {
      state.search = e.target.value;
      render();
    });
    document.getElementById('system-filter-seg').addEventListener('change', (e) => {
      if (e.target.name === 'sysfilter') { state.filterSystem = e.target.value; render(); }
    });
    document.getElementById('sync-btn').addEventListener('click', triggerSync);
    document.getElementById('add-btn').addEventListener('click', openAddDialog);
  }

  function initToolbar() {
    document.getElementById('view-seg').addEventListener('change', (e) => {
      if (e.target.name === 'viewmode') { state.view = e.target.value; render(); }
    });
    document.getElementById('sort-select').addEventListener('change', (e) => { state.sortKey = e.target.value; render(); });
    document.getElementById('role-select').addEventListener('change', (e) => { state.filterRole = e.target.value; render(); });
  }

  function initGroupsDelegation() {
    document.getElementById('groups-container').addEventListener('click', (e) => {
      const toggleBtn = e.target.closest('[data-action="toggle-group"]');
      if (toggleBtn) {
        const key = toggleBtn.getAttribute('data-group-key');
        state.collapsed[key] = !state.collapsed[key];
        render();
        return;
      }
      const editBtn = e.target.closest('[data-action="edit"]');
      if (editBtn) { openEditDialog(parseInt(editBtn.getAttribute('data-unit-id'), 10)); return; }
      const delBtn = e.target.closest('[data-action="delete"]');
      if (delBtn) { deleteUnit(parseInt(delBtn.getAttribute('data-unit-id'), 10)); return; }
      const statsBtn = e.target.closest('[data-action="show-stats"]');
      if (statsBtn) { openViewDialog(parseInt(statsBtn.getAttribute('data-unit-id'), 10)); return; }
    });
  }

  function initDialogDelegation() {
    const backdrop = document.getElementById('dialog-backdrop');
    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) closeDialog(); });
    document.getElementById('dialog-cancel').addEventListener('click', closeDialog);
    document.getElementById('dialog-save').addEventListener('click', saveDialog);

    document.getElementById('dialog-mode-toggle').addEventListener('click', (e) => {
      const link = e.target.closest('[data-action="switch-mode"]');
      if (!link) return;
      state.dialog.mode = link.getAttribute('data-mode');
      state.dialog.error = null;
      renderDialog();
    });

    const fields = document.getElementById('dialog-fields');

    // Klick: kombobox-resultat väljs
    fields.addEventListener('click', (e) => {
      const result = e.target.closest('[data-action="select-entry"]');
      if (result) { selectEntry(parseInt(result.getAttribute('data-entry-id'), 10)); return; }
    });

    // Skriv-events: rör bara state + riktade DOM-uppdateringar, aldrig en
    // full renderDialog() (skulle bygga om <input>-elementet och tappa
    // fokus/markörposition mitt i skrivandet).
    fields.addEventListener('input', (e) => {
      const d = state.dialog;
      if (!d) return;
      if (e.target.id === 'name-search-input') {
        d.nameQuery = e.target.value;
        if (d.selectedEntry) { d.selectedEntry = null; d.entryId = null; updateSelectedEntryBox(); updateComputedPoints(); }
        runSearch();
      } else if (e.target.id === 'count-input') {
        d.count = e.target.value;
        if (d.mode === 'search') updateComputedPoints();
      } else if (e.target.id === 'custom-name-input') {
        d.customName = e.target.value;
      } else if (e.target.id === 'custom-points-input') {
        d.customPoints = e.target.value;
      }
    });

    fields.addEventListener('focusin', (e) => {
      if (e.target.id === 'name-search-input' && !state.dialog.selectedEntry) updateComboboxDropdown();
    });

    document.addEventListener('click', (e) => {
      if (!state.dialog || state.dialog.mode !== 'search') return;
      if (e.target.closest('.combobox')) return;
      const box = document.getElementById('combobox-results');
      if (box) box.hidden = true;
    });

    fields.addEventListener('change', (e) => {
      const d = state.dialog;
      if (!d) return;
      if (e.target.name === 'draft-system') {
        d.system = e.target.value;
        clearSelection();
        if (d.nameQuery.trim()) runSearch();
      } else if (e.target.name === 'draft-status') {
        d.status = e.target.value;
      } else if (e.target.id === 'photo-input' && e.target.files[0]) {
        uploadPhoto(e.target.files[0]);
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    initNav();
    initToolbar();
    initGroupsDelegation();
    initDialogDelegation();
    initViewDialog();
    loadUnits().catch((e) => {
      document.getElementById('groups-container').innerHTML = `<p class="empty-state">Kunde inte läsa enheter: ${escapeHtml(e.message)}</p>`;
    });
  });
})();
