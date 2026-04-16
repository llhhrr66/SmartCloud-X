export function createId(prefix = 'id'): string {
  const generated = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID().replace(/-/g, '').slice(0, 16)
    : Math.random().toString(36).slice(2, 18);

  return `${prefix}_${generated}`;
}

export function chunkText(text: string, chunkSize = 24): string[] {
  if (!text.trim()) {
    return [];
  }

  const chunks: string[] = [];
  for (let cursor = 0; cursor < text.length; cursor += chunkSize) {
    chunks.push(text.slice(cursor, cursor + chunkSize));
  }

  return chunks;
}

export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      window.clearTimeout(timer);
      reject(new DOMException('Request aborted', 'AbortError'));
    };

    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);

    if (signal) {
      signal.addEventListener('abort', onAbort, { once: true });
    }
  });
}

export function buildConversationTitle(text: string, fallback = '新建会话'): string {
  const normalized = text.trim().replace(/\s+/g, ' ');
  return normalized ? normalized.slice(0, 24) : fallback;
}
