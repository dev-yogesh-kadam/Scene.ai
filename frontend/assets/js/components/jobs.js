// The list of queue rows, used on the Create and Queue pages.

import { api } from '../api.js';
import { el, duration } from '../dom.js';
import { refreshJobs } from '../store.js';

const STATUS = { queued: 'Waiting', running: 'Running', done: 'Done', failed: 'Failed', cancelled: 'Cancelled' };

export function jobList(jobs, { limit } = {}) {
  const shown = limit ? jobs.slice(0, limit) : jobs;
  if (!shown.length) return el('div', { class: 'empty' }, 'Nothing in the queue.');
  return el('div', {}, shown.map((job) => {
    const active = job.status === 'queued' || job.status === 'running';
    let detail = [job.error, job.cost > 0 && job.status !== 'done' && 'credits refunded'].filter(Boolean).join(' · ');
    if (job.status === 'running') {
      detail = [job.clips > 1 && `Clip ${job.clip} of ${job.clips}`, job.steps ? `Step ${job.step} of ${job.steps}` : 'Starting…', job.node,
        job.eta_seconds != null && `about ${duration(job.eta_seconds)} left`].filter(Boolean).join(' · ');
    } else if (job.status === 'queued') {
      detail = [`Position ${job.position} in the queue`, job.est_seconds && `estimated ${duration(job.est_seconds)}`].filter(Boolean).join(' · ');
    } else if (job.status === 'done') {
      detail = `Finished in ${duration(job.finished - job.started)}` + (job.cost ? ` · ${job.cost} credits` : '');
    }
    const remove = () => api('/api/jobs/' + job.id, { method: 'DELETE' }).then(refreshJobs).catch((e) => alert(e.message));
    return el('div', { class: 'job' },
      el('div', { class: 'job-head' },
        el('span', { class: 'name' }, job.name),
        el('span', { class: 'pill ' + job.status }, STATUS[job.status]),
        el('button', { class: 'btn small quiet', onclick: remove }, active ? 'Cancel' : 'Remove')),
      el('div', { class: 'sub' }, [job.workflow.split('/')[1].replace(/_/g, ' '), job.summary].filter(Boolean).join(' · ')),
      job.status === 'running' && el('div', { class: 'bar' + (job.steps ? '' : ' busy') },
        el('div', { style: job.steps ? `width:${Math.round(100 * (Math.max(job.clip, 1) - 1 + job.step / job.steps) / Math.max(job.clips, 1))}%` : '' })),
      el('div', { class: 'sub' + (job.status === 'failed' ? ' error' : '') }, detail));
  }));
}
