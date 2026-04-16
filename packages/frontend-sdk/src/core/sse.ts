import { ApiError, extractEnvelopeRetryAfterMs, resolveSseReconnectDelayMs } from './envelope';
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
  getReconnectDelayMsFromEvent?: (event: TEvent) => number | undefined;
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

function resolveReconnectDelayFromEvent<TEvent>(
  event: TEvent,
  getReconnectDelayMsFromEvent?: (event: TEvent) => number | undefined
): number | undefined {
  const extracted = getReconnectDelayMsFromEvent?.(event);
  if (typeof extracted === 'number' && Number.isFinite(extracted) && extracted >= 0) {
    return extracted;
  }

  if (
    typeof event === 'object' &&
    event !== null &&
    'retry' in event &&
    typeof (event as { retry?: unknown }).retry === 'number'
  ) {
    const retry = (event as { retry: number }).retry;
    return Number.isFinite(retry) && retry >= 0 ? retry : undefined;
  }

  return undefined;
}

export async function consumeSseStreamWithReconnect<TEvent>(
  options: ConsumeSseStreamWithReconnectOptions<TEvent>
): Promise<ConsumeSseStreamWithReconnectResult> {
  const maxReconnectAttempts = Math.max(options.maxReconnectAttempts ?? 0, 0);
  const waitForDelay = options.waitForDelay ?? waitForAbortableDelay;
  let reconnectAttempts = 0;
  let reconnectDelayOverrideMs: number | undefined;

  while (true) {
    if (options.signal?.aborted) {
      throw createAbortError();
    }

    const controller = new AbortController();
    const unlinkAbort = linkAbortSignal(options.signal, controller);

    try {
      for await (const event of options.connect(controller.signal, reconnectAttempts)) {
        const eventReconnectDelayMs = resolveReconnectDelayFromEvent(
          event,
          options.getReconnectDelayMsFromEvent
        );
        if (eventReconnectDelayMs !== undefined) {
          reconnectDelayOverrideMs = eventReconnectDelayMs;
        }
        await options.consumeEvent(event);
      }
    } catch (error) {
      if (isAbortError(error)) {
        throw error;
      }

      if (reconnectAttempts >= maxReconnectAttempts) {
        throw error;
      }

      const explicitErrorDelayMs =
        error instanceof ApiError ? error.retryAfterMs : extractEnvelopeRetryAfterMs(error);
      const reconnectDelayMs = resolveSseReconnectDelayMs({
        attempt: reconnectAttempts + 1,
        defaultMs: options.defaultDelayMs,
        maxMs: options.maxDelayMs,
        error
      });
      if (reconnectDelayMs === null) {
        throw error;
      }
      const delayMs = explicitErrorDelayMs ?? reconnectDelayOverrideMs ?? reconnectDelayMs;

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

    const delayMs =
      reconnectDelayOverrideMs ??
      resolveSseReconnectDelayMs({
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
