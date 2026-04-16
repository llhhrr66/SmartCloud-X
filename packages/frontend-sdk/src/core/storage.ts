export interface BrowserStorageStore<T> {
  get(): T | null;
  set(value: T): void;
  clear(): void;
  subscribe(listener: () => void): () => void;
}

export interface BrowserStorageStoreOptions<T> {
  storageKey: string;
  eventName?: string;
  storage?: Storage;
  deserialize?: (raw: string) => T | null;
  serialize?: (value: T) => string;
}

export function createBrowserStorageStore<T>(
  options: BrowserStorageStoreOptions<T>
): BrowserStorageStore<T> {
  const eventName = options.eventName ?? `${options.storageKey}:changed`;
  const getStorage = (): Storage | undefined => {
    if (typeof window === 'undefined') {
      return undefined;
    }

    return options.storage ?? window.localStorage;
  };

  const deserialize = options.deserialize ?? ((raw: string) => JSON.parse(raw) as T);
  const serialize = options.serialize ?? ((value: T) => JSON.stringify(value));

  const dispatch = () => {
    if (typeof window === 'undefined') {
      return;
    }

    window.dispatchEvent(new CustomEvent(eventName));
  };

  return {
    get(): T | null {
      const storage = getStorage();
      if (!storage) {
        return null;
      }

      try {
        const raw = storage.getItem(options.storageKey);
        if (!raw) {
          return null;
        }

        return deserialize(raw);
      } catch {
        return null;
      }
    },

    set(value: T): void {
      const storage = getStorage();
      if (!storage) {
        return;
      }

      storage.setItem(options.storageKey, serialize(value));
      dispatch();
    },

    clear(): void {
      const storage = getStorage();
      if (!storage) {
        return;
      }

      storage.removeItem(options.storageKey);
      dispatch();
    },

    subscribe(listener: () => void): () => void {
      if (typeof window === 'undefined') {
        return () => undefined;
      }

      const handleChange = () => listener();
      const handleStorage = (event: StorageEvent) => {
        const storage = getStorage();
        if (!storage || event.storageArea !== storage || event.key !== options.storageKey) {
          return;
        }

        listener();
      };

      window.addEventListener(eventName, handleChange);
      window.addEventListener('storage', handleStorage);
      return () => {
        window.removeEventListener(eventName, handleChange);
        window.removeEventListener('storage', handleStorage);
      };
    }
  };
}
