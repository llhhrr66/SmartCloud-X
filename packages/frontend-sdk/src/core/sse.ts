import { ApiError, resolveSseReconnectDelayMs } from './envelope';
import { isAbortError, waitForAbortableDelay } from './utils';

export interface ConsumeSseStreamReconnectContext {
  attempt: number;
  maxReconnectAttempts: number;
  delayMs: number;
  error?: unknown;
  reason: 'error' | 'close';
}

export interface ConsumeSseStreamWithReconnectOptions<TEvent> {
  connect: (signal: AbortSignal, attempt: number) => AsyncIterable<TEvent>;
  consumeEvent: (event: TEvent) => void | Promise<void>;
  signal?: AbortSignal;
  maxReconnectAttempts?: number;
  defaultDelayMs?: number;
  maxDelayMs?: number;
  shouldReconnectOnClose?: () => boolean;
  onBeforeReconnect?: (context: ConsumeSseStreamReconnectContext) => void | Promise<void>;
  waitForDelay?: (delayMs: number, signal: AbortSignal) => Promise<void>;
  buildDisconnectError?: (context: {
    reconnectAttempts: number;
    maxReconnectAttempts: number;
  }) => Error;
}

export interface ConsumeSseStreamWithReconnectResult {
  reconnectAttempts: number;
}

function createAbortError(): Error {
  try {
    return new DOMException('Aborted', 'AbortError');
  } catch {
    const error = new Error('Aborted');
    error.name = 'AbortError';
    return error;
  }
}

function linkAbortSignal(parent: AbortSignal | undefined, controller: AbortController): () => void {
  if (!parent) {
    return () => undefined;
  }

  if (parent.aborted) {
    controller.abort();
    return () => undefined;
  }

  const handleAbort = () => controller.abort();
  parent.addEventListener('abort', handleAbort, { once: true });
  return () => parent.removeEventListener('abort', handleAbort);
}

export async function consumeSseStreamWithReconnect<TEvent>(
  options: ConsumeSseStreamWithReconnectOptions<TEvent>
): Promise<ConsumeSseStreamWithReconnectResult> {
  const maxReconnectAttempts = Math.max(options.maxReconnectAttempts ?? 0, 0);
  const waitForDelay = options.waitForDelay ?? waitForAbortableDelay;
  let reconnectAttempts = 0;

  while (true) {
    if (options.signal?.aborted) {
      throw createAbortError();
    }

    const controller = new AbortController();
    const unlinkAbort = linkAbortSignal(options.signal, controller);

    try {
      for await (const event of options.connect(controller.signal, reconnectAttempts)) {
        await options.consumeEvent(event);
      }
    } catch (error) {
      if (isAbortError(error)) {
        throw error;
      }

      if (reconnectAttempts >= maxReconnectAttempts) {
        throw error;
      }

      const delayMs = resolveSseReconnectDelayMs({
        attempt: reconnectAttempts + 1,
        defaultMs: options.defaultDelayMs,
        maxMs: options.maxDelayMs,
        error
      });
      if (delayMs === null) {
        throw error;
      }

      reconnectAttempts += 1;
      await options.onBeforeReconnect?.({
        attempt: reconnectAttempts,
        maxReconnectAttempts,
        delayMs,
        error,
        reason: 'error'
      });
      await waitForDelay(delayMs, options.signal ?? controller.signal);
      continue;
    } finally {
      unlinkAbort();
    }

    if (!options.shouldReconnectOnClose?.()) {
      return { reconnectAttempts };
    }

    if (reconnectAttempts >= maxReconnectAttempts) {
      throw (
        options.buildDisconnectError?.({
          reconnectAttempts,
          maxReconnectAttempts
        }) ??
        new ApiError(
          `SSE stream disconnected after ${maxReconnectAttempts} reconnect attempts`,
          502,
          'SSE_STREAM_DISCONNECTED'
        )
      );
    }

    const delayMs = resolveSseReconnectDelayMs({
      attempt: reconnectAttempts + 1,
      defaultMs: options.defaultDelayMs,
      maxMs: options.maxDelayMs
    });

    reconnectAttempts += 1;
    await options.onBeforeReconnect?.({
      attempt: reconnectAttempts,
      maxReconnectAttempts,
      delayMs: delayMs ?? 0,
      reason: 'close'
    });
    await waitForDelay(delayMs ?? 0, options.signal ?? controller.signal);
  }
}
