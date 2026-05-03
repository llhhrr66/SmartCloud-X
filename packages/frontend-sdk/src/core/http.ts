import {
  ApiError,
  createApiError,
  parseResponsePayload,
  parseSseBlock,
  resolveEnvelopeStatus,
  unwrapEnvelope,
  type RawSseEvent
} from './envelope';
import {
  createRequestId,
  isAbortError,
  isNetworkErrorLike,
  joinUrl,
  shouldDefaultJsonContentType
} from './utils';

export interface HeaderBuildContext {
  path: string;
  expectsStream: boolean;
  init: RequestInit;
}

export interface FrontendApiClientOptions {
  baseUrl: string;
  requestTimeoutMs?: number;
  fetchFn?: typeof fetch;
  buildHeaders?: (context: HeaderBuildContext) => HeadersInit | void;
  shouldRefreshSession?: (status: number, payload: unknown) => boolean;
  refreshSession?: () => Promise<unknown>;
  requestIdPrefix?: string;
}

export function createTransportApiError(
  error: unknown,
  requestId: string | undefined,
  fallbackMessage: string,
  status = 500
): ApiError {
  const resolvedStatus = isNetworkErrorLike(error) ? 503 : status;
  return new ApiError(
    error instanceof Error ? `${fallbackMessage}: ${error.message}` : fallbackMessage,
    resolvedStatus,
    undefined,
    error,
    requestId
  );
}

export class FrontendApiClient {
  private readonly baseUrl: string;
  private readonly requestTimeoutMs: number;
  private readonly fetchFn: typeof fetch;
  private readonly buildHeadersHook?: (context: HeaderBuildContext) => HeadersInit | void;
  private readonly shouldRefreshSession?: (status: number, payload: unknown) => boolean;
  private readonly refreshSessionHook?: () => Promise<unknown>;
  private readonly requestIdPrefix: string;

  constructor(options: FrontendApiClientOptions) {
    this.baseUrl = options.baseUrl;
    this.requestTimeoutMs = options.requestTimeoutMs ?? 30_000;
    const resolvedFetch = options.fetchFn ?? globalThis.fetch;
    this.fetchFn = ((input: RequestInfo | URL, init?: RequestInit) =>
      resolvedFetch.call(globalThis, input, init)) as typeof fetch;
    this.buildHeadersHook = options.buildHeaders;
    this.shouldRefreshSession = options.shouldRefreshSession;
    this.refreshSessionHook = options.refreshSession;
    this.requestIdPrefix = options.requestIdPrefix ?? 'req';
  }

  private buildHeaders(path: string, init: RequestInit, expectsStream = false): Headers {
    const merged = new Headers(init.headers);

    if (!merged.has('Accept')) {
      merged.set('Accept', expectsStream ? 'text/event-stream' : 'application/json');
    }

    if (!merged.has('Content-Type') && shouldDefaultJsonContentType(init.body)) {
      merged.set('Content-Type', 'application/json');
    }

    const extraHeaders = this.buildHeadersHook?.({ path, expectsStream, init });
    if (extraHeaders) {
      const normalized = new Headers(extraHeaders);
      normalized.forEach((value, key) => {
        if (!merged.has(key)) {
          merged.set(key, value);
        }
      });
    }

    if (!merged.has('X-Request-Id')) {
      merged.set('X-Request-Id', createRequestId(this.requestIdPrefix));
    }

    return merged;
  }

  private async maybeRefreshSession(
    status: number,
    payload: unknown,
    allowRefresh: boolean
  ): Promise<boolean> {
    if (!allowRefresh || !this.shouldRefreshSession || !this.refreshSessionHook) {
      return false;
    }

    if (!this.shouldRefreshSession(status, payload)) {
      return false;
    }

    const refreshed = await this.refreshSessionHook();
    return Boolean(refreshed);
  }

  private createTransportError(
    error: unknown,
    requestId: string | undefined,
    fallbackMessage: string,
    status = 500
  ): ApiError {
    return createTransportApiError(error, requestId, fallbackMessage, status);
  }

  async request<T>(path: string, init: RequestInit = {}, allowRefresh = true): Promise<T> {
    const requestHeaders = this.buildHeaders(path, init);
    const requestId = requestHeaders.get('X-Request-Id') ?? undefined;
    const controller = new AbortController();
    const onAbort = () => controller.abort();

    if (init.signal?.aborted) {
      controller.abort();
    } else if (init.signal) {
      init.signal.addEventListener('abort', onAbort, { once: true });
    }

    const timeout = globalThis.setTimeout(() => controller.abort(), this.requestTimeoutMs);

    try {
      const response = await this.fetchFn(joinUrl(this.baseUrl, path), {
        ...init,
        headers: requestHeaders,
        signal: controller.signal
      });

      const payload = await parseResponsePayload(response);
      const refreshStatus = resolveEnvelopeStatus(payload, response.status);
      if (await this.maybeRefreshSession(refreshStatus, payload, allowRefresh)) {
        return this.request<T>(path, init, false);
      }

      if (!response.ok) {
        throw createApiError(payload, response.status, response, undefined, requestId);
      }

      return unwrapEnvelope<T>(payload, response.status, response, requestId);
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }

      if (isAbortError(error)) {
        throw new ApiError('Request timed out or was aborted', 408, undefined, undefined, requestId);
      }

      throw this.createTransportError(error, requestId, 'Network request failed');
    } finally {
      globalThis.clearTimeout(timeout);
      init.signal?.removeEventListener('abort', onAbort);
    }
  }

  async *stream(path: string, init: RequestInit = {}, allowRefresh = true): AsyncGenerator<RawSseEvent> {
    const requestHeaders = this.buildHeaders(path, init, true);
    const requestId = requestHeaders.get('X-Request-Id') ?? undefined;
    let response: Response;

    try {
      response = await this.fetchFn(joinUrl(this.baseUrl, path), {
        ...init,
        headers: requestHeaders,
        signal: init.signal
      });
    } catch (error) {
      if (isAbortError(error)) {
        throw error;
      }

      throw this.createTransportError(error, requestId, 'SSE stream request failed', 503);
    }

    const responseContentType = (response.headers.get('content-type') ?? '').toLowerCase();
    const isJsonEnvelopeResponse = responseContentType.includes('json');

    if (!response.ok || isJsonEnvelopeResponse) {
      const payload = await parseResponsePayload(response);
      const refreshStatus = resolveEnvelopeStatus(payload, response.status);

      if (await this.maybeRefreshSession(refreshStatus, payload, allowRefresh)) {
        yield* this.stream(path, init, false);
        return;
      }

      if (!response.ok) {
        throw createApiError(payload, response.status, response, undefined, requestId);
      }

      unwrapEnvelope<unknown>(payload, response.status, response, requestId);
      throw createApiError(
        payload,
        refreshStatus,
        response,
        'Expected SSE stream response',
        requestId
      );
    }

    if (!response.body) {
      throw new ApiError('SSE stream body is empty', response.status, undefined, undefined, requestId);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() ?? '';

        for (const block of blocks) {
          const parsed = parseSseBlock(block);
          if (parsed) {
            yield parsed;
          }
        }
      }

      buffer += decoder.decode();

      if (buffer.trim()) {
        const parsed = parseSseBlock(buffer);
        if (parsed) {
          yield parsed;
        }
      }
    } catch (error) {
      if (isAbortError(error)) {
        throw error;
      }

      throw this.createTransportError(error, requestId, 'SSE stream interrupted', 503);
    }
  }
}

export function createApiClient(options: FrontendApiClientOptions): FrontendApiClient {
  return new FrontendApiClient(options);
}
