import test from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';

import {
  createDerivedPort,
  findAvailablePort,
  resolvePlaywrightPorts,
  resolvePortCachePath
} from './port-utils.mjs';

test('prefers explicit env ports when both are valid and distinct', () => {
  const ports = resolvePlaywrightPorts({
    appPortEnv: '41000',
    apiPortEnv: '41001',
    pid: 512
  });

  assert.deepEqual(ports, {
    appPort: 41000,
    apiPort: 41001
  });
});

test('derives stable non-default ports from pid when env ports are absent', () => {
  const ports = resolvePlaywrightPorts({
    pid: 777
  });

  assert.equal(ports.appPort, createDerivedPort(34100, 777));
  assert.equal(ports.apiPort, createDerivedPort(38100, 777));
  assert.notEqual(ports.appPort, 3100);
  assert.notEqual(ports.apiPort, 38090);
});

test('avoids reusing the same derived port for both servers', () => {
  const ports = resolvePlaywrightPorts({
    appPortEnv: '42000',
    apiPortEnv: '42000',
    pid: 900
  });

  assert.equal(ports.appPort, 42000);
  assert.notEqual(ports.apiPort, 42000);
  assert.equal(ports.apiPort, createDerivedPort(38100, 900));
});

test('skips an occupied port and returns the next available candidate', async () => {
  const occupiedPort = 45100;
  const server = net.createServer();

  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(occupiedPort, '127.0.0.1', resolve);
  });

  try {
    const nextPort = await findAvailablePort(occupiedPort, {
      host: '127.0.0.1',
      maxAttempts: 5
    });

    assert.notEqual(nextPort, occupiedPort);
    assert.equal(nextPort, occupiedPort + 1);
  } finally {
    await new Promise((resolve, reject) => {
      server.close((error) => {
        if (error) {
          reject(error);
          return;
        }
        resolve();
      });
    });
  }
});

test('scopes cache paths to a single test run identifier', () => {
  const firstPath = resolvePortCachePath('run-a');
  const secondPath = resolvePortCachePath('run-b');

  assert.notEqual(firstPath, secondPath);
  assert.match(firstPath, /run-a/);
  assert.match(secondPath, /run-b/);
});
