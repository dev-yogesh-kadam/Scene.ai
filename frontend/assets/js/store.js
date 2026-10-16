// Shared state: the signed-in user, the live queue and the render server status.

import { api } from './api.js';

export const store = {
  user: null,
  jobs: [],
  online: null,
  people: null,  // how many people have the studio open now; sent to admins only, as it changes
  rerun: null,   // a library item whose settings the Create page should load
  prefill: null, // {slot, ref}: a reference the Create page should put into a slot (e.g. the first frame)
  from: null,    // the page that opened Create ('#/canvas'), so Create can offer a way back to it
};

const listeners = new Set();
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function emit(change) { for (const fn of [...listeners]) fn(change); }

export async function refreshJobs() {
  store.jobs = (await api('/api/jobs')).jobs;
  emit('jobs');
}

export async function refreshStatus() {
  try { store.online = (await api('/api/status')).online; } catch (e) { store.online = false; }
  emit('status');
}

let socket = null;
let timers = [];
// Which page this tab shows, for the admin's list of who is online.
const sayPage = () => { if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ page: location.hash.split('?')[0] })); };

export function startLive() {
  stopLive();
  const connect = () => {
    socket = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/api/events');
    socket.onopen = sayPage;
    socket.onmessage = (e) => {
      const message = JSON.parse(e.data);
      if (message.online_users != null) {   // someone opened the studio or closed their last tab
        store.people = message.online_users;
        return emit('people');
      }
      store.jobs = message.jobs;
      emit('jobs');
      if (store.user && message.credits != null && message.credits !== store.user.credits) {
        store.user.credits = message.credits;
        emit('credits');
      }
      if (message.library_changed) emit('library');
    };
    socket.onclose = () => { if (store.user) timers.push(setTimeout(connect, 3000)); };
  };
  connect();
  window.addEventListener('hashchange', sayPage);
  refreshStatus();
  timers.push(setInterval(refreshStatus, 15000));
  // Fallback if the live connection is down.
  timers.push(setInterval(() => { if (!socket || socket.readyState !== WebSocket.OPEN) refreshJobs().catch(() => {}); }, 4000));
}

export function stopLive() {
  window.removeEventListener('hashchange', sayPage);
  timers.forEach((t) => { clearTimeout(t); clearInterval(t); });
  timers = [];
  if (socket) { socket.onclose = null; socket.close(); socket = null; }
}
