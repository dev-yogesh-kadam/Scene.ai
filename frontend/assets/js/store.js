// Shared state: the signed-in user, the live queue and the render server status.

import { api } from './api.js';
import { here } from './nav.js';

export const store = {
  user: null,
  jobs: [],
  online: null,
  rerun: null,   // a library item whose settings the Create page should load
  reuseSeed: null, // with rerun: the seed it was made with, which the Create page keeps ("Reuse seed")
  prefill: null, // {slot, ref}: a reference the Create page should put into a slot (e.g. the first frame)
  from: null,    // the page that opened Create ('/canvas'), so Create can offer a way back to it
};

const listeners = new Set();
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function emit(change) { for (const fn of [...listeners]) fn(change); }

export async function refreshJobs() {
  store.jobs = (await api('/api/jobs')).jobs;
  emit('jobs');
}

export async function refreshStatus() {
  try {
    const found = await api('/api/status');
    store.online = found.online;
    store.page = found.page;   // the version of the page files on the server; a tab that loaded older ones offers to reload
  } catch (e) { store.online = false; }
  emit('status');
}

let socket = null;
let timers = [];
let heard = 0;   // when the live connection last said anything
// A connection can die without closing (the computer slept, the network changed): the page would keep showing jobs as
// they were. So it pings every PING ms, and one that has said nothing for SILENT ms is replaced, the jobs fetched anew.
const PING = 20000;
const SILENT = 50000;
// Which page this tab shows, for the admin's list of who is online.
const sayPage = () => { if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ page: here() })); };

export function startLive() {
  stopLive();
  const connect = () => {
    socket = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/api/events');
    heard = Date.now();
    socket.onopen = sayPage;
    socket.onmessage = (e) => {
      heard = Date.now();
      const message = JSON.parse(e.data);
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
  window.addEventListener('scene:route', sayPage);
  refreshStatus();
  timers.push(setInterval(refreshStatus, 15000));
  timers.push(setInterval(() => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    if (Date.now() - heard > SILENT) {   // gone quiet: the jobs fetched now, and a new connection at once
      refreshJobs().catch(() => {});
      const dead = socket;
      dead.onclose = null;   // closing a dead connection may take long to say so: the new one does not wait for it
      dead.close();
      connect();
      return;
    }
    socket.send(JSON.stringify({ ping: 1 }));
  }, PING));
  // Fallback if the live connection is down.
  timers.push(setInterval(() => { if (!socket || socket.readyState !== WebSocket.OPEN) refreshJobs().catch(() => {}); }, 4000));
}

export function stopLive() {
  window.removeEventListener('scene:route', sayPage);
  timers.forEach((t) => { clearTimeout(t); clearInterval(t); });
  timers = [];
  if (socket) { socket.onclose = null; socket.close(); socket = null; }
}
