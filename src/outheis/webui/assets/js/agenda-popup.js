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
    btn_cancel: 'Cancel',
    btn_save: 'Save',
    btn_delete: 'Delete',
    btn_done: 'Done',
    placeholder_tags: '#tag1 #tag2',
    placeholder_deps: 'Item titles, comma-separated',
    confirm_delete: 'Delete this item?',
    conflict_blocked: '⚠ Blocked by predecessors. Effective day:'
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
   */
  function showPopup(options) {
    const {
      item = null,
      allItems: items = [],
      facets: facetList = [],
      onSave: saveCallback,
      getExcludeId: excludeIdFn,
      initialDate
    } = options;

    // Close existing popup
    closePopup();

    // Store state
    currentItem = item;
    allItems = items;
    facets = facetList;
    onSave = saveCallback;
    getExcludeId = excludeIdFn;

    const isEdit = item !== null;

    // Create overlay
    const overlay = document.createElement('div');
    overlay.className = 'popup-overlay show';
    overlay.onclick = closePopup;

    // Build facet options
    const facetOpts = facets
      .filter(f => f.id !== 'none')
      .map(f => `<option value="${f.id}"${item && item.facet === f.id ? ' selected' : ''}>${f.label || f.id}</option>`)
      .join('');

    // Get initial values for edit
    let date1 = '';
    let date2 = '';
    let startTime = '';
    let endTime = '';
    let sizeVal = 'm';

    if (isEdit && item) {
      // Extract dates from tags or item
      const tags = item.tags || [];
      const dateTags = tags.filter(t => t.startsWith('#date-')).map(t => t.slice(6));
      date1 = dateTags[0] || (item.start ? item.start.slice(0, 10) : '') || (item.date || '');
      date2 = dateTags[1] || '';

      // Extract times
      const timeTag = tags.find(t => t.startsWith('#time-'));
      if (timeTag) {
        const parts = timeTag.slice(6).split('-');
        startTime = parts[0] || '';
        endTime = parts[1] || '';
      } else if (item.start && item.end) {
        startTime = item.start.length > 10 ? item.start.slice(11, 16) : item.start;
        endTime = item.end.length > 10 ? item.end.slice(11, 16) : item.end;
      }

      // Size
      sizeVal = item.size || 'm';
    } else {
      // Default for create
      date1 = initialDate || new Date().toISOString().slice(0, 10);
    }

    // Create popup element
    const popup = document.createElement('div');
    popup.className = 'popup';
    popup.onclick = e => e.stopPropagation();
    popup.innerHTML = `
      <div class="popup-title" id="ap-title">${isEdit ? I18N.title_edit : I18N.title_create}</div>
      <div class="popup-conflict" id="ap-conflict" style="display:none;"></div>
      <textarea class="popup-textarea" id="ap-item-title" placeholder="${I18N.label_title}" rows="2">${isEdit && item ? escapeHtml(item.title || '') : ''}</textarea>

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
          </div>
        </div>
      </div>

      <div class="popup-field" style="margin-bottom:10px;">
        <span class="popup-label">${I18N.label_tags}</span>
        <input class="popup-input" id="ap-tags" placeholder="${I18N.placeholder_tags}" value="${isEdit && item ? escapeHtml((item.tags || []).join(' ')) : ''}">
      </div>

      <div class="popup-field" style="margin-bottom:10px;">
        <span class="popup-label">${I18N.label_follows}</span>
        <input class="popup-input" id="ap-follows" placeholder="${I18N.placeholder_deps}" value="${isEdit && item ? escapeHtml((item.follows || []).join(', ')) : ''}">
      </div>
      <div class="popup-field" style="margin-bottom:10px;">
        <span class="popup-label">${I18N.label_precedes}</span>
        <input class="popup-input" id="ap-precedes" placeholder="${I18N.placeholder_deps}" value="${isEdit && item ? escapeHtml((item.precedes || []).join(', ')) : ''}">
      </div>
      <div class="popup-field" style="margin-bottom:10px;">
        <span class="popup-label">${I18N.label_relates}</span>
        <input class="popup-input" id="ap-relates" placeholder="${I18N.placeholder_deps}" value="${isEdit && item ? escapeHtml((item.relates || []).join(', ')) : ''}">
      </div>

      <div class="popup-buttons">
        ${isEdit ? `<button class="btn" id="ap-delete" style="color:#c44;border-color:#c44;margin-right:auto;">${I18N.btn_delete}</button>` : ''}
        <button class="btn" onclick="window.AgendaPopup.close()">${I18N.btn_cancel}</button>
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

    // Save button handler
    popup.querySelector('#ap-save').onclick = handleSave;

    // Delete button handler (edit mode only)
    const deleteBtn = popup.querySelector('#ap-delete');
    if (deleteBtn) {
      deleteBtn.onclick = handleDelete;
    }

    // Focus title
    setTimeout(() => popup.querySelector('#ap-item-title').focus(), 0);
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

    // Build item data
    const itemData = {
      id: currentItem ? currentItem.id || currentItem._id : generateId(),
      title,
      facet: facet || null,
      size: size !== 'm' ? size : null,
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