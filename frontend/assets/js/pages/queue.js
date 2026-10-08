// The Queue page: every recent job of the user.

import { api } from '../api.js';
import { el } from '../dom.js';
import { store, subscribe, refreshJobs } from '../store.js';
import { jobList } from '../components/jobs.js';

export function render(view) {
  const list = el('div');
  const clear = el('button', { class: 'btn small', onclick: async () => {
    for (const job of store.jobs) {
      if (!['queued', 'running'].includes(job.status)) await api('/api/jobs/' + job.id, { method: 'DELETE' }).catch(() => {});
    }
    refreshJobs();
  } }, 'Clear finished');
  view.replaceChildren(
    el('div', { class: 'page-head' }, el('h1', {}, 'Queue'), clear),
    el('p', { class: 'page-sub' }, 'Jobs run one at a time on the render server, in the order they were added.'),
    el('div', { class: 'card' }, list));
  const draw = () => {
    list.replaceChildren(jobList(store.jobs));
    clear.classList.toggle('hidden', !store.jobs.some((j) => !['queued', 'running'].includes(j.status)));
  };
  draw();
  return subscribe((change) => { if (change === 'jobs') draw(); });
}
