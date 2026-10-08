// Calls to the Scene.ai backend.

export async function api(path, options = {}) {
  if (options.json !== undefined) {
    options = { ...options, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(options.json) };
  }
  const response = await fetch(path, { credentials: 'same-origin', ...options });
  const body = await response.json().catch(() => ({}));
  if (response.status === 401 && !path.startsWith('/api/auth/')) {
    window.dispatchEvent(new Event('scene:signed-out'));
  }
  if (!response.ok) {
    const detail = Array.isArray(body.detail) ? 'Some fields are missing or wrong.' : body.detail;
    const error = new Error(detail || `Request failed (${response.status})`);
    error.status = response.status;
    error.data = body;   // the whole answer, for a page that needs more than the message (the sign-in's second step)
    throw error;
  }
  return body;
}
