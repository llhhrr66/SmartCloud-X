import { readJson, storageKeys, writeJson } from './storage';

type TaskKind = 'research' | 'poster' | 'icp';

interface TaskRegistry {
  research: string[];
  poster: string[];
  icp: string[];
}

const defaultRegistry: TaskRegistry = {
  research: [],
  poster: [],
  icp: []
};

function readRegistry(): TaskRegistry {
  return readJson<TaskRegistry>(storageKeys.taskRegistry, defaultRegistry);
}

function writeRegistry(registry: TaskRegistry): void {
  writeJson(storageKeys.taskRegistry, registry);
}

export function listTaskIds(kind: TaskKind): string[] {
  return readRegistry()[kind];
}

export function rememberTask(kind: TaskKind, taskId: string, limit = 12): void {
  const registry = readRegistry();
  const nextIds = [taskId, ...registry[kind].filter((item) => item !== taskId)].slice(0, limit);
  writeRegistry({
    ...registry,
    [kind]: nextIds
  });
}
