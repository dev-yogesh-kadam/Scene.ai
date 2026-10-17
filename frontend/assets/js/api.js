// Calls to the Scene.ai backend.

// A call answered as it works, one JSON object per line: onLine(object) is called for each line as it arrives.
// Errors before the answer starts are thrown like api() throws them.
export async function apiLines(path, { json, signal } = {}, onLine = () => {}) {
  const response = await fetch(path, { method: 'POST', credentials: 'same-origin', signal, body: JSON.stringify(json),
    headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson' } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401) window.dispatchEvent(new Event('scene:signed-out'));
    const error = new Error((Array.isArray(body.detail) ? 'Some fields are missing or wrong.' : body.detail) || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    let cut;
    while ((cut = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, cut).trim();
      buffer = buffer.slice(cut + 1);
      if (line) onLine(JSON.parse(line));
    }
    if (done) break;
  }
  if (buffer.trim()) onLine(JSON.parse(buffer));
}

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
