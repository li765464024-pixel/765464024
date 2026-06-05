/* ==========================================
   复盘工具 — JavaScript 核心逻辑
   ========================================== */

// ===== State =====
const STORAGE_KEY = 'retro-board-cards';
let cards = [];

let editingId = null; // id of the card being edited

// ===== DOM refs =====
const $ = (s, ctx = document) => ctx.querySelector(s);
const $$ = (s, ctx = document) => [...ctx.querySelectorAll(s)];

const lists = {
  good: $('#list-good'),
  improve: $('#list-improve'),
  action: $('#list-action'),
};

const counts = {
  good: $('#count-good'),
  improve: $('#count-improve'),
  action: $('#count-action'),
};

// Modal — Add
const modalOverlay = $('#modalOverlay');
const modalClose = $('#modalClose');
const modalCancel = $('#modalCancel');
const modalConfirm = $('#modalConfirm');
const cardText = $('#cardText');
const cardType = $('#cardType');

// Modal — Edit
const editOverlay = $('#editModalOverlay');
const editClose = $('#editModalClose');
const editCancel = $('#editModalCancel');
const editConfirm = $('#editModalConfirm');
const editText = $('#editText');
const editType = $('#editType');

// Toolbar
const exportBtn = $('#exportBtn');
const importBtn = $('#importBtn');
const importFileInput = $('#importFileInput');
const clearBtn = $('#clearBtn');

// ===== Data helpers =====
function loadData() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      cards = JSON.parse(raw);
      if (!Array.isArray(cards)) cards = [];
    } else {
      cards = [];
    }
  } catch {
    cards = [];
  }
}

function saveData() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cards));
}

function generateId() {
  return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 6);
}

// ===== Render =====
function render() {
  // Group cards by type
  const grouped = { good: [], improve: [], action: [] };
  for (const c of cards) {
    if (grouped[c.type]) {
      grouped[c.type].push(c);
    }
  }

  // Render each column
  for (const type of /** @type {const} */ (['good', 'improve', 'action'])) {
    const list = lists[type];
    const countEl = counts[type];
    const items = grouped[type];

    list.innerHTML = '';
    countEl.textContent = items.length;

    if (items.length === 0) {
      list.classList.add('card-list--empty');
    } else {
      list.classList.remove('card-list--empty');
    }

    for (const card of items) {
      const el = document.createElement('div');
      el.className = `card card-${card.type}`;
      el.draggable = true;
      el.dataset.id = card.id;

      // Drag events
      el.addEventListener('dragstart', onDragStart);
      el.addEventListener('dragend', onDragEnd);

      // Text
      const textSpan = document.createElement('span');
      textSpan.className = 'card-text';
      textSpan.textContent = card.text;
      el.appendChild(textSpan);

      // Edit button
      const editBtn = document.createElement('button');
      editBtn.className = 'card-edit-trigger';
      editBtn.innerHTML = '✎';
      editBtn.title = '编辑';
      editBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openEditModal(card.id);
      });
      el.appendChild(editBtn);

      // Delete button
      const delBtn = document.createElement('button');
      delBtn.className = 'card-delete';
      delBtn.innerHTML = '×';
      delBtn.title = '删除';
      delBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteCard(card.id);
      });
      el.appendChild(delBtn);

      list.appendChild(el);
    }
  }
}

// ===== CRUD =====
function addCard(text, type) {
  const card = {
    id: generateId(),
    text: text.trim(),
    type,
    createdAt: Date.now(),
  };
  cards.push(card);
  saveData();
  render();
}

function deleteCard(id) {
  cards = cards.filter(c => c.id !== id);
  saveData();
  render();
}

function updateCard(id, text, type) {
  const card = cards.find(c => c.id === id);
  if (card) {
    card.text = text.trim();
    card.type = type;
    saveData();
    render();
  }
}

// ===== Modal — Add =====
function openAddModal(type) {
  cardText.value = '';
  cardType.value = type || 'good';
  modalOverlay.classList.add('active');
  cardText.focus();
}

function closeAddModal() {
  modalOverlay.classList.remove('active');
}

modalClose.addEventListener('click', closeAddModal);
modalCancel.addEventListener('click', closeAddModal);
modalOverlay.addEventListener('click', (e) => {
  if (e.target === modalOverlay) closeAddModal();
});

modalConfirm.addEventListener('click', () => {
  const text = cardText.value.trim();
  if (!text) {
    cardText.focus();
    cardText.style.outline = '2px solid #ef4444';
    setTimeout(() => cardText.style.outline = '', 800);
    return;
  }
  const type = cardType.value;
  addCard(text, type);
  closeAddModal();
});

// Enter key to confirm (in textarea — Ctrl+Enter)
cardText.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    modalConfirm.click();
  }
});

// ===== Modal — Edit =====
function openEditModal(id) {
  const card = cards.find(c => c.id === id);
  if (!card) return;
  editingId = id;
  editText.value = card.text;
  editType.value = card.type;
  editOverlay.classList.add('active');
  editText.focus();
}

function closeEditModal() {
  editOverlay.classList.remove('active');
  editingId = null;
}

editClose.addEventListener('click', closeEditModal);
editCancel.addEventListener('click', closeEditModal);
editOverlay.addEventListener('click', (e) => {
  if (e.target === editOverlay) closeEditModal();
});

editConfirm.addEventListener('click', () => {
  if (!editingId) return;
  const text = editText.value.trim();
  if (!text) {
    editText.focus();
    editText.style.outline = '2px solid #ef4444';
    setTimeout(() => editText.style.outline = '', 800);
    return;
  }
  const type = editType.value;
  updateCard(editingId, text, type);
  closeEditModal();
});

editText.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    editConfirm.click();
  }
});

// ===== "Add Card" buttons on columns =====
document.querySelectorAll('.btn-add-card').forEach(btn => {
  btn.addEventListener('click', () => {
    openAddModal(btn.dataset.type);
  });
});

// ===== Drag & Drop =====
let dragSrcId = null;

function onDragStart(e) {
  dragSrcId = this.dataset.id;
  this.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', this.dataset.id);
  // Don't show the ghost image
}

function onDragEnd() {
  this.classList.remove('dragging');
  document.querySelectorAll('.card-list').forEach(el => el.classList.remove('drag-over'));
  dragSrcId = null;
}

// Set up drag-over / drop on each card-list
for (const type of ['good', 'improve', 'action']) {
  const list = lists[type];

  list.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    list.classList.add('drag-over');
  });

  list.addEventListener('dragleave', () => {
    list.classList.remove('drag-over');
  });

  list.addEventListener('drop', (e) => {
    e.preventDefault();
    list.classList.remove('drag-over');
    const draggedId = e.dataTransfer.getData('text/plain');
    if (!draggedId || draggedId === dragSrcId) return;

    // Find the dragged card
    const srcIdx = cards.findIndex(c => c.id === draggedId);
    if (srcIdx === -1) return;

    // If dropped in a different column, change type
    // If same column, reorder (insert near drop position)
    const targetType = type;
    const draggedCard = cards[srcIdx];

    // Calculate new index within the target array
    const targetCards = cards.filter(c => c.type === targetType);
    const dropIndex = targetCards.length; // default: append to end

    // Try to figure out the drop position relative to existing cards
    const dropCardElements = list.querySelectorAll('.card');
    let insertBeforeIndex = dropIndex;
    for (let i = 0; i < dropCardElements.length; i++) {
      const rect = dropCardElements[i].getBoundingClientRect();
      const midY = rect.top + rect.height / 2;
      if (e.clientY < midY) {
        insertBeforeIndex = i;
        break;
      }
    }

    // Remove from old position
    cards.splice(srcIdx, 1);

    // Determine new position
    const sameTypeCards = cards.filter(c => c.type === targetType);
    // If we moved within same column, insertBeforeIndex is correct
    // If we moved from different column, insertBeforeIndex is relative to the target cards before removal
    
    let insertPos;
    if (draggedCard.type === targetType) {
      // Same column: insertBeforeIndex is based on current render order (before removal adjusted)
      // After splice, the rendered positions shifted
      insertPos = 0;
      let count = 0;
      for (let i = 0; i < cards.length; i++) {
        if (cards[i].type === targetType) {
          if (count === insertBeforeIndex) {
            insertPos = i;
            break;
          }
          count++;
        }
      }
      if (count < insertBeforeIndex) {
        // Append
        insertPos = cards.length;
        for (let i = cards.length - 1; i >= 0; i--) {
          if (cards[i].type === targetType) {
            insertPos = i + 1;
            break;
          }
        }
      }
    } else {
      // Different column: find position after the last card of targetType before drop point
      let count = 0;
      insertPos = cards.length;
      for (let i = 0; i < cards.length; i++) {
        if (cards[i].type === targetType) {
          if (count === insertBeforeIndex) {
            insertPos = i;
            break;
          }
          count++;
        }
      }
    }

    // Update type and insert
    draggedCard.type = targetType;
    cards.splice(insertPos, 0, draggedCard);

    saveData();
    render();
  });
}

// ===== Export JSON =====
function exportData() {
  const json = JSON.stringify(cards, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const date = new Date().toISOString().slice(0, 10);
  a.download = `复盘数据_${date}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

exportBtn.addEventListener('click', exportData);

// ===== Import JSON =====
importBtn.addEventListener('click', () => {
  importFileInput.click();
});

importFileInput.addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (evt) => {
    try {
      const imported = JSON.parse(evt.target.result);
      if (!Array.isArray(imported)) throw new Error('格式错误');
      // Validate each item
      for (const item of imported) {
        if (!item.id || !item.text || !item.type) {
          throw new Error('数据字段不完整');
        }
        if (!['good', 'improve', 'action'].includes(item.type)) {
          throw new Error('分类无效: ' + item.type);
        }
      }
      // Merge: append imported, filter out duplicates by id
      const existingIds = new Set(cards.map(c => c.id));
      const newCards = imported.filter(c => !existingIds.has(c.id));
      if (newCards.length === 0) {
        alert('导入完成，但没有新数据（所有卡片已存在）。');
        return;
      }
      cards = cards.concat(newCards);
      saveData();
      render();
      alert(`成功导入 ${newCards.length} 张卡片！`);
    } catch (err) {
      alert('导入失败：文件格式不正确。\n' + err.message);
    }
  };
  reader.readAsText(file);
  // Reset so the same file can be re-imported
  importFileInput.value = '';
});

// ===== Clear All =====
clearBtn.addEventListener('click', () => {
  if (cards.length === 0) return;
  if (!confirm('确定要清空所有卡片吗？此操作不可撤销。')) return;
  cards = [];
  saveData();
  render();
});

// ===== Keyboard shortcut =====
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (editOverlay.classList.contains('active')) closeEditModal();
    else if (modalOverlay.classList.contains('active')) closeAddModal();
  }
});

// ===== Init =====
loadData();
render();
