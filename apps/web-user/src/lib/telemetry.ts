import { useSyncExternalStore } from 'react';
import { createRequestId } from './request-meta';
import { readAuthSession, readJson, storageKeys, writeJson } from './storage';

export type TelemetryEventName =
  | 'page_view'
  | 'login_submit'
  | 'api_error'
  | 'permission_denied'
  | 'chat_stream_start'
  | 'chat_stream_end'
  | 'chat_stream_error';

type TelemetryMetadataValue = string | number | boolean | null;

export interface TelemetryEvent {
  id: string;
  eventName: TelemetryEventName;
  page: string;
  requestId: string;
  userId?: string;
  conversationId?: string;
  errorCode?: string;
  createdAt: string;
  metadata?: Record<string, TelemetryMetadataValue>;
}

export interface TelemetryStoreState {
  events: TelemetryEvent[];
}

interface RecordTelemetryEventInput {
  eventName: TelemetryEventName;
  page?: string;
  requestId?: string;
  userId?: string;
  conversationId?: string;
  errorCode?: string | number;
  metadata?: Record<string, unknown>;
  dedupeKey?: string;
}

type Listener = () => void;
type StateUpdater<T> = T | ((previous: T) => T);

const MAX_STORED_EVENTS = 40;
const DEDUPE_WINDOW_MS = 1_500;
const recentDedupeKeys = new Map<string, number>();

function createStore<T>(createInitialState: () => T) {
  let state = createInitialState();
  const listeners = new Set<Listener>();

  return {
    getSnapshot(): T {
      return state;
    },
    subscribe(listener: Listener): () => void {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    setState(nextState: StateUpdater<T>): void {
      state = typeof nextState === 'function' ? (nextState as (previous: T) => T)(state) : nextState;
      listeners.forEach((listener) => listener());
    }
  };
}

function readInitialState(): TelemetryStoreState {
  return {
    events: readJson<TelemetryEvent[]>(storageKeys.telemetry, [])
  };
}

function persistEvents(events: TelemetryEvent[]): void {
  writeJson(storageKeys.telemetry, events);
}

function readCurrentPage(): string {
  if (typeof window === 'undefined') {
    return '/';
  }

  return `${window.location.pathname}${window.location.search}`;
}

function readCurrentUserId(): string | undefined {
  return readAuthSession()?.user.userId;
}

function sanitizeMetadataValue(value: unknown): TelemetryMetadataValue | undefined {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
  ) {
    return value;
  }

  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join(', ');
  }

  if (value && typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch {
      return '[unserializable]';
    }
  }

  return undefined;
}

function sanitizeMetadata(
  metadata?: Record<string, unknown>
): Record<string, TelemetryMetadataValue> | undefined {
  if (!metadata) {
    return undefined;
  }

  const entries = Object.entries(metadata).flatMap(([key, value]) => {
    const sanitizedValue = sanitizeMetadataValue(value);
    return sanitizedValue === undefined ? [] : ([[key, sanitizedValue]] as const);
  });

  if (!entries.length) {
    return undefined;
  }

  return Object.fromEntries(entries);
}

function cleanupRecentDedupeKeys(now: number): void {
  recentDedupeKeys.forEach((timestamp, key) => {
    if (now - timestamp > DEDUPE_WINDOW_MS) {
      recentDedupeKeys.delete(key);
    }
  });
}

const telemetryStore = createStore(readInitialState);

export function useTelemetryStore(): TelemetryStoreState {
  return useSyncExternalStore(telemetryStore.subscribe, telemetryStore.getSnapshot, telemetryStore.getSnapshot);
}

export function recordTelemetryEvent(input: RecordTelemetryEventInput): TelemetryEvent | null {
  const now = Date.now();
  cleanupRecentDedupeKeys(now);

  if (input.dedupeKey) {
    const previousTimestamp = recentDedupeKeys.get(input.dedupeKey);
    if (previousTimestamp && now - previousTimestamp < DEDUPE_WINDOW_MS) {
      return null;
    }

    recentDedupeKeys.set(input.dedupeKey, now);
  }

  const event: TelemetryEvent = {
    id: createRequestId('tel'),
    eventName: input.eventName,
    page: input.page ?? readCurrentPage(),
    requestId: input.requestId ?? createRequestId('evt'),
    userId: input.userId ?? readCurrentUserId(),
    conversationId: input.conversationId,
    errorCode: input.errorCode === undefined ? undefined : String(input.errorCode),
    createdAt: new Date(now).toISOString(),
    metadata: sanitizeMetadata(input.metadata)
  };

  telemetryStore.setState((previous) => {
    const nextEvents = [event, ...previous.events].slice(0, MAX_STORED_EVENTS);
    persistEvents(nextEvents);
    return {
      events: nextEvents
    };
  });

  if (typeof console !== 'undefined') {
    console.info('[telemetry]', event.eventName, event);
  }

  return event;
}

export function clearTelemetryEvents(): void {
  telemetryStore.setState({
    events: []
  });
  persistEvents([]);
}
