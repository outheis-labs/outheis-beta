/**
 * Shared agenda item popup component
 * Used by both flow.html and agenda.html
 */

(function(global) {
  'use strict';

  // State
  let activePopup = null;
  let currentItem = null;
  let allItems = [];
  let facets = [];
  let onSave = null;
  let getExcludeId = null;
  let currentInstanceDate = null;

  // I18N defaults (can be overridden)
  const I18N = {
    title_edit: 'Edit item',
    title_create: 'Add item',
    label_title: 'Title',
    label_start: 'Start',
    label_end: 'End',
    label_day1: 'Day',
    label_day2: 'Day 2',
    label_facet: 'Facet',
    label_size: 'Size',
    label_tags: 'Tags',
    label_follows: 'Waits for (follows)',
    label_precedes: 'Blocks (precedes)',
    label_relates: 'Relates to',
    label_dependencies: 'Dependencies',
    label_follows_short: 'Follows',
    label_precedes_short: 'Precedes',
    label_relates_short: 'Relates',
    btn_cancel: 'Cancel',
    btn_save: 'Save',
    btn_delete: 'Delete',
    btn_done: 'Done',
    btn_ok: 'OK',
    placeholder_tags: '#tag1 #tag2',
    placeholder_deps: 'Item titles, comma-separated',
    placeholder_note: 'Note (optional)',
    confirm_delete: 'Delete this item?',
    conflict_blocked: '⚠ Blocked by predecessors. Effective day:',
    done_title: 'Done',
    label_scope: 'Scope',
    scope_instance: 'Instance',
    scope_series: 'Series',
    btn_select: 'Select',
    search_placeholder: 'Search items...',
    no_items: 'No items found'
  };

  /**
   * Show the popup for creating or editing an item
   * @param {Object} options
   * @param {Object|null} options.item - Existing item to edit (null for create)
   * @param {Array} options.allItems - All items (for dependency selection)
   * @param {Array} options.facets - Available facets
   * @param {Function} options.onSave - Callback when saving (receives item data)
   * @param {Function} options.getExcludeId - Function returning current item ID for exclusion
   * @param {string} options.initialDate - Initial date for create (YYYY-MM-DD)
   * @param {string} options.instanceDate - For recurring items: the specific instance date (YYYY-MM-DD)
   */
  function showPopup(options) {
    const {
      item = null,
      allItems: items = [],
      facets: facetList = [],
      onSave: saveCallback,
      getExcludeId: excludeIdFn,
      initialDate,
      instanceDate
    } = options;

    // Close existing popup
    closePopup();

    // Store state
    currentItem = item;
    allItems = items;
    facets = facetList;
    onSave = saveCallback;
    getExcludeId = excludeIdFn;
    currentInstanceDate = instanceDate || null;

    const isEdit = item !== null;
    console.log('[AgendaPopup] showPopup called, isEdit:', isEdit, 'item:', item);

    // Create overlay
    const overlay = document.createElement('div');
    overlay.className = 'popup-overlay show';
    overlay.onclick = closePopup;

    // Get initial values for edit
    let date1 = '';
    let date2 = '';
    let startTime = '';
    let endTime = '';
    let sizeVal = null;
    let facetVal = '';

    if (isEdit && item) {
      // Debug
      console.log('[AgendaPopup] item.tags:', item.tags, 'type:', typeof item.tags);

      // Extract dates from tags or item
      // Handle tags as array, string, or other formats
      let tags = [];
      if (Array.isArray(item.tags)) {
        console.log('[AgendaPopup] tags is array');
        tags = item.tags;
      } else if (typeof item.tags === 'string') {
        console.log('[AgendaPopup] tags is string:', item.tags);
        tags = item.tags.split(/\s+/).filter(t => t);
        console.log('[AgendaPopup] after split:', tags);
      } else if (item.tags && typeof item.tags === 'object') {
        console.log('[AgendaPopup] tags is object');
        // Handle edge case: tags might be an object
        try { tags = Object.values(item.tags); } catch(e) { tags = []; }
      } else {
        console.log('[AgendaPopup] tags is unexpected:', item.tags);
      }

      const dateTags = tags.filter(t => typeof t === 'string' && t.startsWith('#date-')).map(t => t.slice(6));
      date1 = dateTags[0] || (item.start ? item.start.slice(0, 10) : '') || (item.date || '');
      date2 = dateTags[1] || '';

      // Extract times
      const timeTag = tags.find(t => typeof t === 'string' && t.startsWith('#time-'));
      if (timeTag) {
        const parts = timeTag.slice(6).split('-');
        startTime = parts[0] || '';
        endTime = parts[1] || '';
      } else if (item.start && item.end) {
        startTime = item.start.length > 10 ? item.start.slice(11, 16) : item.start;
        endTime = item.end.length > 10 ? item.end.slice(11, 16) : item.end;
      }

      // Extract facet from property or tags
      if (item.facet && item.facet !== 'none') {
        facetVal = item.facet;
        console.log('[AgendaPopup] facet from property:', facetVal);
      } else {
        const facetTag = tags.find(t => typeof t === 'string' && t.startsWith('#facet-'));
        if (facetTag) {
          facetVal = facetTag.slice(7); // Remove '#facet-'
          console.log('[AgendaPopup] facet from tags:', facetVal);
        }
      }

      // Extract size from property or tags
      if (item.size) {
        sizeVal = item.size;
        console.log('[AgendaPopup] size from property:', sizeVal);
      } else {
        const sizeTag = tags.find(t => typeof t === 'string' && t.startsWith('#size-'));
        if (sizeTag) {
          sizeVal = sizeTag.slice(6); // Remove '#size-'
          console.log('[AgendaPopup] size from tags:', sizeVal);
        }
      }
      console.log('[AgendaPopup] Final facetVal:', facetVal, 'sizeVal:', sizeVal, 'tags:', tags);
    } else {
      // Default for create
      date1 = initialDate || new Date().toISOString().slice(0, 10);
    }

    // Build facet options
    const facetOpts = facets
      .filter(f => f.id !== 'none')
      .map(f => `<option value="${f.id}"${facetVal === f.id ? ' selected' : ''}>${f.label || f.id}</option>`)
      .join('');

    // Create popup element
    // Check if item is recurring
    const itemTags = Array.isArray(item?.tags) ? item.tags :
                     (typeof item?.tags === 'string' ? item.tags.split(/\s+/).filter(t => t) : []);
    const isRecurring = itemTags.some(t => typeof t === 'string' && t.startsWith('#recurring-'));

    const popup = document.createElement('div');
    popup.className = 'popup';
    popup.onclick = e => e.stopPropagation();
    popup.innerHTML = `
      <div class="popup-title" id="ap-title">${isEdit ? I18N.title_edit : I18N.title_create}</div>
      <div class="popup-conflict" id="ap-conflict" style="display:none;"></div>
      <textarea class="popup-textarea" id="ap-item-title" placeholder="${I18N.label_title}" rows="2">${isEdit && item ? escapeHtml(item.title || '') : ''}</textarea>

      ${isRecurring ? `
      <div class="popup-field" style="margin-bottom:10px;">
        <span class="popup-label">${I18N.label_scope}</span>
        <div class="popup-radios" id="ap-scope">
          <label><input type="radio" name="ap-scope" value="instance" checked>${I18N.scope_instance}</label>
          <label><input type="radio" name="ap-scope" value="series">${I18N.scope_series}</label>
        </div>
      </div>
      ` : ''}

      <div class="popup-row">
        <div class="popup-field">
          <span class="popup-label">${I18N.label_start}</span>
          <input class="popup-input" id="ap-start" type="time" value="${startTime}">
        </div>
        <div class="popup-field">
          <span class="popup-label">${I18N.label_end}</span>
          <input class="popup-input" id="ap-end" type="time" value="${endTime}">
        </div>
      </div>

      <div class="popup-row">
        <div class="popup-field">
          <span class="popup-label">${I18N.label_day1}</span>
          <input class="popup-input" id="ap-day1" type="date" value="${date1}">
        </div>
        <div class="popup-field">
          <span class="popup-label">${I18N.label_day2}</span>
          <input class="popup-input" id="ap-day2" type="date" value="${date2}">
        </div>
      </div>

      <div class="popup-row">
        <div class="popup-field">
          <span class="popup-label">${I18N.label_facet}</span>
          <select class="popup-input" id="ap-facet">
            <option value="">none</option>
            ${facetOpts}
          </select>
        </div>
        <div class="popup-field">
          <span class="popup-label">${I18N.label_size}</span>
          <div class="popup-radios" id="ap-size">
            <label><input type="radio" name="ap-size" value="s" ${sizeVal === 's' ? 'checked' : ''}>S</label>
            <label><input type="radio" name="ap-size" value="m" ${sizeVal === 'm' ? 'checked' : ''}>M</label>
            <label><input type="radio" name="ap-size" value="l" ${sizeVal === 'l' ? 'checked' : ''}>L</label>
            <label><input type="radio" name="ap-size" value="" ${!sizeVal ? 'checked' : ''}>none</label>
          </div>
        </div>
      </div>

      <div class="popup-field" style="margin-bottom:10px;">
        <span class="popup-label">${I18N.label_tags}</span>
        <input class="popup-input" id="ap-tags" placeholder="${I18N.placeholder_tags}" value="${isEdit && item ? escapeHtml(getAllTags(item)) : ''}">
      </div>

      <div class="popup-field" style="margin-bottom:10px;">
        <span class="popup-label">${I18N.label_dependencies}</span>
        <div class="popup-deps">
          <button class="btn" id="ap-follows-btn" type="button">${I18N.label_follows_short} (${((item && item.follows) || []).length})</button>
          <button class="btn" id="ap-precedes-btn" type="button">${I18N.label_precedes_short} (${((item && item.precedes) || []).length})</button>
          <button class="btn" id="ap-relates-btn" type="button">${I18N.label_relates_short} (${((item && item.relates) || []).length})</button>
        </div>
        <input type="hidden" id="ap-follows" value="${isEdit && item ? escapeHtml((item.follows || []).join(',')) : ''}">
        <input type="hidden" id="ap-precedes" value="${isEdit && item ? escapeHtml((item.precedes || []).join(',')) : ''}">
        <input type="hidden" id="ap-relates" value="${isEdit && item ? escapeHtml((item.relates || []).join(',')) : ''}">
      </div>

      <div class="popup-buttons">
        ${isEdit ? `<button class="btn" id="ap-delete" style="color:#c44;border-color:#c44;margin-right:auto;">${I18N.btn_delete}</button>` : ''}
        <button class="btn" onclick="window.AgendaPopup.close()">${I18N.btn_cancel}</button>
        ${isEdit ? `<button class="btn" id="ap-done" style="background:hsl(178, 60%, 48%);border-color:hsl(178, 60%, 48%);color:#fff;">${I18N.btn_done}</button>` : ''}
        <button class="btn btn-primary" id="ap-save">${I18N.btn_save}</button>
      </div>
    `;

    document.body.appendChild(overlay);
    document.body.appendChild(popup);
    activePopup = popup;

    // Show conflict indicator if blocked
    if (isEdit && item && item.effectiveDay !== undefined && item.effectiveDay > (item.day || 0)) {
      const conflictEl = popup.querySelector('#ap-conflict');
      conflictEl.style.display = 'block';
      conflictEl.textContent = `${I18N.conflict_blocked} day ${item.effectiveDay}`;
    }

    // Button handlers
    popup.querySelector('#ap-save').onclick = handleSave;
    const doneBtn = popup.querySelector('#ap-done');
    if (doneBtn) {
      doneBtn.onclick = handleDone;
    }

    // Delete button handler (edit mode only)
    const deleteBtn = popup.querySelector('#ap-delete');
    if (deleteBtn) {
      deleteBtn.onclick = handleDelete;
    }

    // Dependency selection buttons
    setupDependencyButton('follows', 'ap-follows-btn', 'ap-follows', 'label_follows_short');
    setupDependencyButton('precedes', 'ap-precedes-btn', 'ap-precedes', 'label_precedes_short');
    setupDependencyButton('relates', 'ap-relates-btn', 'ap-relates', 'label_relates_short');

    // Update tags when facet or size changes
    const facetSelect = document.getElementById('ap-facet');
    const tagsInput = document.getElementById('ap-tags');

    facetSelect.onchange = () => {
      const newFacet = facetSelect.value;
      let tags = tagsInput.value.split(/[\s,]+/).filter(t => t && !t.startsWith('#facet-'));
      if (newFacet && newFacet !== 'none') {
        tags.push(`#facet-${newFacet}`);
      }
      tagsInput.value = tags.join(' ');
    };

    document.querySelectorAll('input[name="ap-size"]').forEach(radio => {
      radio.onchange = () => {
        const newSize = radio.value;
        let tags = tagsInput.value.split(/[\s,]+/).filter(t => t && !t.startsWith('#size-'));
        if (newSize) {
          tags.push(`#size-${newSize}`);
        }
        tagsInput.value = tags.join(' ');
      };
    });

    // Focus title
    setTimeout(() => popup.querySelector('#ap-item-title').focus(), 0);
  }

  /**
   * Setup dependency selection button
   */
  function setupDependencyButton(type, btnId, inputId, labelKey) {
    const btn = document.getElementById(btnId);
    if (!btn) return;

    btn.onclick = () => {
      const currentValues = (document.getElementById(inputId).value || '').split(',').filter(Boolean);
      showItemSelector(type, currentValues, (selected) => {
        document.getElementById(inputId).value = selected.join(',');
        // Update button count
        btn.textContent = `${I18N[labelKey]} (${selected.length})`;
      });
    };
  }

  /**
   * Show item selection popup
   */
  function showItemSelector(type, selectedIds, onConfirm) {
    const excludeId = getExcludeId ? getExcludeId() : null;

    // Create overlay
    const overlay = document.createElement('div');
    overlay.className = 'selector-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    // Create popup
    const popup = document.createElement('div');
    popup.className = 'selector-popup';
    popup.onclick = (e) => e.stopPropagation();

    // Filter items: exclude current item and done items
    const availableItems = allItems.filter(item => {
      if (excludeId && item.id === excludeId) return false;
      const tags = Array.isArray(item.tags) ? item.tags : [];
      if (tags.some(t => typeof t === 'string' && t.startsWith('#done-'))) return false;
      return true;
    });

    // Sort: selected items first, then unselected
    const selectedItems = availableItems.filter(item => selectedIds.includes(item.id));
    const unselectedItems = availableItems.filter(item => !selectedIds.includes(item.id));

    // Build item list HTML
    const selectedHtml = selectedItems.map(item => `
      <label class="selector-item selector-item-selected">
        <input type="checkbox" value="${escapeHtml(item.id)}" checked>
        <span class="selector-item-title">${escapeHtml(item.title || 'Untitled')}</span>
        <span class="selector-item-id">${escapeHtml(item.id)}</span>
      </label>
    `).join('');

    const unselectedHtml = unselectedItems.map(item => `
      <label class="selector-item">
        <input type="checkbox" value="${escapeHtml(item.id)}">
        <span class="selector-item-title">${escapeHtml(item.title || 'Untitled')}</span>
        <span class="selector-item-id">${escapeHtml(item.id)}</span>
      </label>
    `).join('');

    const separatorHtml = selectedItems.length > 0 && unselectedItems.length > 0
      ? '<hr class="selector-separator">'
      : '';

    popup.innerHTML = `
      <div class="selector-header">
        <input type="text" class="selector-search" id="selector-search" placeholder="${I18N.search_placeholder}">
      </div>
      <div class="selector-list" id="selector-list">
        ${selectedHtml}
        ${separatorHtml}
        ${unselectedHtml}
      </div>
      <div class="selector-buttons">
        <button class="btn" id="selector-cancel">${I18N.btn_cancel}</button>
        <button class="btn btn-primary" id="selector-ok">${I18N.btn_ok}</button>
      </div>
    `;

    overlay.appendChild(popup);
    document.body.appendChild(overlay);

    // Search functionality
    const searchInput = popup.querySelector('#selector-search');
    const listContainer = popup.querySelector('#selector-list');

    searchInput.oninput = () => {
      const query = searchInput.value.toLowerCase().trim();
      const items = listContainer.querySelectorAll('.selector-item, .selector-separator');
      items.forEach(el => {
        if (el.classList.contains('selector-separator')) {
          el.style.display = '';
          return;
        }
        const title = el.querySelector('.selector-item-title').textContent.toLowerCase();
        const id = el.querySelector('.selector-item-id').textContent.toLowerCase();
        const match = !query || title.includes(query) || id.includes(query);
        el.style.display = match ? '' : 'none';
      });
    };

    // Focus search
    setTimeout(() => searchInput.focus(), 0);

    // Button handlers
    popup.querySelector('#selector-cancel').onclick = () => overlay.remove();
    popup.querySelector('#selector-ok').onclick = () => {
      const checked = Array.from(listContainer.querySelectorAll('input:checked')).map(cb => cb.value);
      onConfirm(checked);
      overlay.remove();
    };

    // Keyboard: Enter to confirm, Escape to cancel
    searchInput.onkeydown = (e) => {
      if (e.key === 'Enter') popup.querySelector('#selector-ok').click();
      if (e.key === 'Escape') overlay.remove();
    };
  }

  function handleSave() {
    const title = document.getElementById('ap-item-title').value.trim();
    if (!title) {
      const inp = document.getElementById('ap-item-title');
      inp.focus();
      inp.style.outline = '2px solid #c44';
      setTimeout(() => { inp.style.outline = ''; }, 1500);
      return;
    }

    const d1 = document.getElementById('ap-day1').value;
    const d2 = document.getElementById('ap-day2').value;
    const t1 = document.getElementById('ap-start').value;
    const t2 = document.getElementById('ap-end').value;
    const facet = document.getElementById('ap-facet').value;
    const size = document.querySelector('input[name="ap-size"]:checked').value;
    const tagsRaw = document.getElementById('ap-tags').value.trim();
    const follows = document.getElementById('ap-follows').value.split(',').map(s => s.trim()).filter(Boolean);
    const precedes = document.getElementById('ap-precedes').value.split(',').map(s => s.trim()).filter(Boolean);
    const relates = document.getElementById('ap-relates').value.split(',').map(s => s.trim()).filter(Boolean);

    // Check scope for recurring items
    const scopeRadio = document.querySelector('input[name="ap-scope"]:checked');
    const scope = scopeRadio ? scopeRadio.value : 'instance';
    const isInstanceMode = scope === 'instance';

    // Build item data
    const itemData = {
      id: currentItem ? currentItem.id || currentItem._id : generateId(),
      title,
      facet: facet || null,
      size: size || null,
      follows: follows.length ? follows : null,
      precedes: precedes.length ? precedes : null,
      relates: relates.length ? relates : null,
      tags: [],
      date: d1 || null,
      date2: d2 || null,
      start: t1 || null,
      end: t2 || null
    };

    // Parse additional tags
    const extraTags = tagsRaw ? tagsRaw.split(/[\s,]+/).map(t => t.trim()).filter(t => t.startsWith('#')) : [];
    itemData.extraTags = extraTags;

    // For recurring items in instance mode: mark as new standalone instance
    const itemTags = Array.isArray(currentItem?.tags) ? currentItem.tags : [];
    const isRecurring = itemTags.some(t => typeof t === 'string' && t.startsWith('#recurring-'));
    if (isRecurring && isInstanceMode) {
      itemData._newInstance = true;
      itemData.id = generateId(); // New ID for standalone instance
      itemData._instanceDate = currentInstanceDate; // Pass instance date for exception
    }

    // Call save callback
    if (onSave) {
      onSave(itemData, currentItem);
    }

    closePopup();
  }

  function handleDelete() {
    if (!confirm(I18N.confirm_delete)) return;

    if (onSave) {
      onSave(null, currentItem); // null indicates delete
    }

    closePopup();
  }

  function handleDone() {
    // Show commit message overlay
    const overlay = document.createElement('div');
    overlay.className = 'done-overlay';
    overlay.innerHTML = `
      <div class="done-dialog">
        <div class="done-title">${I18N.done_title}</div>
        <input type="text" class="done-input" id="done-note" placeholder="${I18N.placeholder_note}" autofocus>
        <div class="done-buttons">
          <button class="btn" onclick="this.closest('.done-overlay').remove()">${I18N.btn_cancel}</button>
          <button class="btn btn-primary" id="done-confirm">${I18N.btn_ok}</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const input = overlay.querySelector('#done-note');
    const confirmBtn = overlay.querySelector('#done-confirm');

    // Focus input immediately
    setTimeout(() => input.focus(), 0);

    // Handle confirm
    function confirmDone() {
      const note = input.value.trim();

      // Mark item as done with today's date
      const today = new Date().toISOString().slice(0, 10);

      // Get current tags (handle array, string, and edge cases)
      let itemTags = [];
      if (Array.isArray(currentItem.tags)) {
        itemTags = [...currentItem.tags];
      } else if (typeof currentItem.tags === 'string') {
        itemTags = currentItem.tags.split(/\s+/).filter(t => t);
      } else if (currentItem.tags && typeof currentItem.tags === 'object') {
        try { itemTags = Object.values(currentItem.tags); } catch(e) { itemTags = []; }
      }

      // Detect if recurring
      const isRecurring = itemTags.some(t => typeof t === 'string' && t.startsWith('#recurring-'));

      // Add #done-YYYY-MM-DD if not present
      const doneTag = `#done-${today}`;
      if (!itemTags.find(t => t === doneTag)) {
        itemTags.push(doneTag);
      }

      // Add note as tag if provided
      if (note) {
        const noteTag = note.replace(/\s+/g, '-');
        if (!itemTags.find(t => t === `#${noteTag}`)) {
          itemTags.push(`#${noteTag}`);
        }
      }

      // Get form values
      const d1 = document.getElementById('ap-day1').value;
      const d2 = document.getElementById('ap-day2').value;
      const t1 = document.getElementById('ap-start').value;
      const t2 = document.getElementById('ap-end').value;
      const facet = document.getElementById('ap-facet').value;
      const size = document.querySelector('input[name="ap-size"]:checked').value;
      const tagsRaw = document.getElementById('ap-tags').value.trim();
      const follows = document.getElementById('ap-follows').value.split(',').map(s => s.trim()).filter(Boolean);
      const precedes = document.getElementById('ap-precedes').value.split(',').map(s => s.trim()).filter(Boolean);
      const relates = document.getElementById('ap-relates').value.split(',').map(s => s.trim()).filter(Boolean);

      // Parse additional tags from input
      const extraTags = tagsRaw ? tagsRaw.split(/[\s,]+/).map(t => t.trim()).filter(t => t.startsWith('#')) : [];

      // For recurring items: remove recurring tag (create standalone instance)
      if (isRecurring) {
        itemTags = itemTags.filter(t => !t.startsWith('#recurring-'));
      }

      // Merge tags
      const mergedTags = [...new Set([
        ...itemTags.filter(t => !t.startsWith('#done-')),
        ...extraTags,
        doneTag
      ])];

      // Build item data
      let itemData = {
        id: currentItem ? currentItem.id || currentItem._id : generateId(),
        title: document.getElementById('ap-item-title').value.trim(),
        facet: facet || null,
        size: size || null,
        follows: follows.length ? follows : null,
        precedes: precedes.length ? precedes : null,
        relates: relates.length ? relates : null,
        tags: mergedTags,
        note: note || null,
        date: d1 || null,
        date2: d2 || null,
        start: t1 || null,
        end: t2 || null,
        done: today
      };

      // For recurring items: create as new standalone instance
      if (isRecurring) {
        itemData._newInstance = true;
        itemData.id = generateId();
        itemData._instanceDate = currentInstanceDate; // Pass instance date for exception
      }

      if (onSave) {
        onSave(itemData, currentItem);
      }

      overlay.remove();
      closePopup();
    }

    confirmBtn.onclick = confirmDone;
    input.onkeydown = (e) => {
      if (e.key === 'Enter') confirmDone();
      if (e.key === 'Escape') overlay.remove();
    };
  }

  function closePopup() {
    if (activePopup) {
      activePopup.remove();
      activePopup = null;
    }
    const overlay = document.querySelector('.popup-overlay.show');
    if (overlay) overlay.remove();

    currentItem = null;
    allItems = [];
    facets = [];
    onSave = null;
    getExcludeId = null;
  }

  function generateId() {
    return String(Date.now()) + String(Math.floor(Math.random() * 10000)).padStart(4, '0');
  }

  function getAllTags(item) {
    // Get tags as array (handle array, string, and edge cases)
    let tags = [];
    if (Array.isArray(item.tags)) {
      tags = [...item.tags];
    } else if (typeof item.tags === 'string') {
      tags = item.tags.split(/\s+/).filter(t => t);
    } else if (item.tags && typeof item.tags === 'object') {
      try { tags = Object.values(item.tags); } catch(e) { tags = []; }
    }

    // Include facet as tag if present
    if (item.facet && item.facet !== 'none') {
      const facetTag = `#facet-${item.facet}`;
      if (!tags.find(t => t === facetTag)) {
        tags.push(facetTag);
      }
    }

    // Include size as tag if present
    if (item.size) {
      const sizeTag = `#size-${item.size}`;
      if (!tags.find(t => t === sizeTag)) {
        tags.push(sizeTag);
      }
    }

    return tags.join(' ');
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Export API
  global.AgendaPopup = {
    show: showPopup,
    close: closePopup,
    I18N
  };

})(window);