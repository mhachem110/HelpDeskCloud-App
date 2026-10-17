'use strict';

const $ = (id) => document.getElementById(id);
const state = { tickets: [], editing: null, requestId: 0 };
const priorityClass = { Low: 'priority-low', Medium: 'priority-medium', High: 'priority-high', Critical: 'priority-critical' };
const statusClass = { Open: 'status-open', 'In Progress': 'status-in-progress', Resolved: 'status-resolved' };
let toastTimer;

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers }
  });
  if (response.status === 204) return null;
  let body;
  try { body = await response.json(); } catch { body = null; }
  if (!response.ok) {
    const details = body?.errors && Object.values(body.errors).flat().join(' ');
    throw new Error(details || body?.error || body?.title || `Request failed (HTTP ${response.status})`);
  }
  return body;
}

function toast(message) {
  $('toast').textContent = message;
  $('toast').classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('toast').classList.remove('show'), 3300);
}

function formatDate(raw) {
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(raw));
}

function node(tag, className, value) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (value !== undefined) result.textContent = value;
  return result;
}

function cell(parent, child) {
  const td = node('td');
  td.append(child);
  parent.append(td);
  return td;
}

function renderTickets() {
  const tbody = $('tickets-body');
  tbody.replaceChildren();
  $('ticket-count').textContent = `${state.tickets.length} ticket${state.tickets.length === 1 ? '' : 's'}`;
  $('result-caption').textContent = `Showing ${state.tickets.length} ticket${state.tickets.length === 1 ? '' : 's'}`;
  $('empty-state').hidden = state.tickets.length !== 0;

  for (const ticket of state.tickets) {
    const tr = node('tr');
    const titleWrap = node('div');
    titleWrap.append(node('span', 'ticket-title', ticket.title));
    titleWrap.append(node('div', 'ticket-code', `#${ticket.id.slice(0, 8).toUpperCase()}`));
    const first = cell(tr, titleWrap);
    first.title = ticket.description || ticket.title;
    cell(tr, node('span', '', ticket.category));
    cell(tr, node('span', `pill ${priorityClass[ticket.priority] || ''}`, ticket.priority));
    cell(tr, node('span', `pill ${statusClass[ticket.status] || ''}`, ticket.status));
    cell(tr, node('span', '', formatDate(ticket.createdAt)));

    const actions = node('div');
    const edit = node('button', 'ticket-action', 'Edit');
    edit.type = 'button';
    edit.setAttribute('aria-label', `Edit ticket ${ticket.title}`);
    edit.addEventListener('click', () => openForm(ticket));
    const del = node('button', 'ticket-action ticket-delete', 'Delete');
    del.type = 'button';
    del.setAttribute('aria-label', `Delete ticket ${ticket.title}`);
    del.addEventListener('click', () => removeTicket(ticket));
    actions.append(edit, del);
    cell(tr, actions);
    tbody.append(tr);
  }
}

function renderStats(stats) {
  $('stat-total').textContent = stats.total;
  $('stat-open').textContent = stats.open;
  $('stat-progress').textContent = stats.inProgress;
  $('stat-resolved').textContent = stats.resolved;
  $('legend-resolved').textContent = stats.resolved;
  $('legend-open').textContent = stats.open;
  $('legend-progress').textContent = stats.inProgress;
  const total = Number(stats.total);
  const resolved = total ? 100 * stats.resolved / total : 0;
  const open = total ? 100 * stats.open / total : 0;
  const progress = total ? 100 * stats.inProgress / total : 0;
  $('resolved-percent').textContent = `${Math.round(resolved)}%`;
  $('donut').style.background = `conic-gradient(#32be8d 0 ${resolved}%, #f2b348 ${resolved}% ${resolved + open}%, #8c79df ${resolved + open}% ${resolved + open + progress}%, #eef1f6 0 100%)`;
}

async function refresh() {
  const currentRequestId = ++state.requestId;
  const query = new URLSearchParams();
  if ($('filter-status').value) query.set('status', $('filter-status').value);
  if ($('filter-priority').value) query.set('priority', $('filter-priority').value);
  if ($('search').value.trim()) query.set('search', $('search').value.trim());
  try {
    const [tickets, stats] = await Promise.all([api(`/tickets?${query}`), api('/tickets/stats')]);
    if (currentRequestId !== state.requestId) return;
    state.tickets = tickets;
    renderTickets();
    renderStats(stats);
  } catch (error) {
    if (currentRequestId !== state.requestId) return;
    $('tickets-body').replaceChildren();
    const row = node('tr');
    const message = cell(row, node('span', '', 'Unable to load tickets. Check the database connection, then refresh.'));
    message.colSpan = 6;
    message.className = 'loading-row';
    $('tickets-body').append(row);
    $('empty-state').hidden = true;
    toast(error.message);
  }
}

function openForm(ticket = null) {
  state.editing = ticket;
  $('ticket-form').reset();
  $('form-error').hidden = true;
  $('status-field').hidden = !ticket;
  $('dialog-title').textContent = ticket ? 'Edit Support Ticket' : 'Create Support Ticket';
  $('save-ticket').textContent = ticket ? 'Save Changes' : 'Create Ticket';
  if (ticket) {
    $('ticket-title').value = ticket.title;
    $('ticket-description').value = ticket.description;
    $('ticket-category').value = ticket.category;
    $('ticket-priority').value = ticket.priority;
    $('ticket-status').value = ticket.status;
  }
  $('ticket-dialog').showModal();
  $('ticket-title').focus();
}

async function submitTicket(event) {
  event.preventDefault();
  const body = {
    title: $('ticket-title').value.trim(),
    description: $('ticket-description').value.trim(),
    category: $('ticket-category').value,
    priority: $('ticket-priority').value
  };
  if (state.editing) body.status = $('ticket-status').value;
  $('save-ticket').disabled = true;
  try {
    await api(state.editing ? `/tickets/${state.editing.id}` : '/tickets', {
      method: state.editing ? 'PUT' : 'POST', body: JSON.stringify(body)
    });
    $('ticket-dialog').close();
    toast(state.editing ? 'Ticket updated successfully.' : 'Ticket created successfully.');
    await refresh();
  } catch (error) {
    $('form-error').textContent = error.message;
    $('form-error').hidden = false;
  } finally { $('save-ticket').disabled = false; }
}

async function removeTicket(ticket) {
  if (!confirm(`Delete "${ticket.title}"? This cannot be undone.`)) return;
  try {
    await api(`/tickets/${ticket.id}`, { method: 'DELETE' });
    toast('Ticket deleted.');
    await refresh();
  } catch (error) { toast(error.message); }
}

$('new-ticket').addEventListener('click', () => openForm());
$('quick-create').addEventListener('click', () => openForm());
$('close-dialog').addEventListener('click', () => $('ticket-dialog').close());
$('cancel-dialog').addEventListener('click', () => $('ticket-dialog').close());
$('ticket-form').addEventListener('submit', submitTicket);
$('filter-status').addEventListener('change', refresh);
$('filter-priority').addEventListener('change', refresh);
let searchTimer;
$('search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(refresh, 280); });
refresh();
