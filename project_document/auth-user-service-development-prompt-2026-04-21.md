# Auth User Service Development Prompt

You are working inside the `SmartCloud-X` repository. Continue improving `apps/auth-user-service` based on the current implementation, status files, and development documents. Do not rebuild the service from scratch.

## Required reading

Read these files first:

- `/home/ljr/SmartCloud/开发文档拆分版/05-服务拆分与前端设计.md`
- `/home/ljr/SmartCloud-X/docs/status/supervisor-auth-marketing-research-status.md`
- `/home/ljr/SmartCloud-X/apps/auth-user-service/README.md`
- `/home/ljr/SmartCloud-X/apps/auth-user-service/app/main.py`
- `/home/ljr/SmartCloud-X/apps/auth-user-service/app/core/config.py`
- `/home/ljr/SmartCloud-X/apps/auth-user-service/app/dependencies.py`
- `/home/ljr/SmartCloud-X/apps/auth-user-service/app/security.py`
- `/home/ljr/SmartCloud-X/apps/auth-user-service/app/models.py`
- `/home/ljr/SmartCloud-X/apps/auth-user-service/app/routes.py`
- `/home/ljr/SmartCloud-X/apps/auth-user-service/app/store.py`
- `/home/ljr/SmartCloud-X/apps/auth-user-service/tests/test_auth_api.py`

## Original service responsibilities

According to the project development document, `auth-user-service` is responsible for:

1. login
2. user
3. permissions
4. user profile

The current implementation already includes password/code login, refresh/logout, forgot/reset password, profile read/update, admin bootstrap auth, internal token validation, permission checks, cache invalidation, database-backed session/revocation/challenge state, and shared JWT compatibility across owned services.

## First step: gap analysis

Before coding, produce a short gap report covering:

- whether the four documented responsibilities are fully covered or only baseline-covered
- whether current user profile is only account profile or a broader business profile
- whether permission handling is fully aligned with gateway/research/marketing usage
- whether README, status file, and tests still match current route behavior
- whether public vs internal auth contracts are consistent
- whether there are any obvious missing tests around RBAC, admin confirmation, invalidation, or token lifecycle

Do not skip this analysis.

## Main objectives for this round

### P1. Strengthen permission and profile coverage

Improve the service only where it is still weak relative to its documented responsibilities.

Focus areas:
- user profile consistency and update validation
- permission enforcement edge cases
- admin/user token lifecycle correctness
- internal token validation correctness after logout, password change, and token-version rotation
- invalidation and cache-related contract behavior

Do not invent a brand-new identity system. Extend the current one.

### P2. Improve tests

Add or improve tests for:
- permission-denied cases
- admin auth happy path and error path
- internal caller allow-list enforcement
- validate-token behavior for revoked or stale tokens
- password reset and logout invalidation edge cases
- profile update edge cases
- runtime health payload assertions when applicable

Use the existing test style in `apps/auth-user-service/tests/test_auth_api.py`.

### P3. Keep persistence behavior correct

Preserve the current database-backed model and the low-frequency prune fix. Do not reintroduce hot-path synchronous pruning behavior that can trigger lock-wait failures.

If you touch persistence logic:
- protect refresh-session correctness
- protect verification-code correctness
- protect password-challenge correctness
- protect revoked-token correctness
- keep SQLite fallback compatibility for local/test only

### P4. Update docs if behavior changes

If you change behavior, update:
- `/home/ljr/SmartCloud-X/apps/auth-user-service/README.md`
- `/home/ljr/SmartCloud-X/docs/status/supervisor-auth-marketing-research-status.md`

Documentation must clearly state:
- implemented auth flows
- internal auth routes
- persistence/runtime mode expectations
- known limitations
- validation commands actually used

## Coding constraints

- Do not redesign the whole auth system.
- Do not break public route names unless there is a documented contract bug.
- Do not weaken token validation.
- Do not remove database-backed runtime behavior.
- Do not add fake compatibility hacks.
- Prefer small, reviewable edits.

## Required validation

Use the repository virtual environment and explicit PYTHONPATH.

### Unit tests
```bash
PYTHONPATH="/home/ljr/SmartCloud-X/apps/auth-user-service:/home/ljr/SmartCloud-X/apps:/home/ljr/SmartCloud-X/packages" \
/home/ljr/SmartCloud-X/.venv/bin/pytest \
/home/ljr/SmartCloud-X/apps/auth-user-service/tests/test_auth_api.py -q
```

### Compile check
```bash
cd /home/ljr/SmartCloud-X && \
/home/ljr/SmartCloud-X/.venv/bin/python -m compileall apps/auth-user-service/app
```

### Broader owned-scope validation if environment is ready
```bash
cd /home/ljr/SmartCloud-X && \
uv run --with-requirements apps/auth-user-service/requirements.txt --with httpx --with pytest \
python -m pytest apps/auth-user-service/tests apps/marketing-service/tests apps/research-service/tests -q
```

## Required final output

Provide:

1. file-by-file change summary
2. service duty completion table:

| Duty | Status | Notes |
|---|---|---|
| login | ... | ... |
| user | ... | ... |
| permissions | ... | ... |
| user profile | ... | ... |

3. exact validation commands run
4. exact results
5. known limitations
6. whether the service is ready to hand back for review

## Relevant official documentation

FastAPI:
- https://fastapi.tiangolo.com/tutorial/security/
- https://fastapi.tiangolo.com/tutorial/dependencies/
- https://fastapi.tiangolo.com/tutorial/testing/

Pydantic:
- https://docs.pydantic.dev/latest/concepts/models/
- https://docs.pydantic.dev/latest/concepts/validators/

SQLAlchemy:
- https://docs.sqlalchemy.org/en/20/orm/quickstart.html
- https://docs.sqlalchemy.org/en/20/core/exceptions.html

Pytest:
- https://docs.pytest.org/en/stable/how-to/fixtures.html
- https://docs.pytest.org/en/stable/how-to/monkeypatch.html

## 停止与上报规则

### 必须立即停止并上报的情况

1. **环境阻塞**：虚拟环境 `.venv` 缺少关键依赖（如 fastapi、sqlalchemy、pydantic）且安装失败时，停止编码，报告缺少的包和错误信息。
2. **编译失败**：`python -m compileall apps/auth-user-service/app` 报语法错误或导入错误时，停止后续开发，先修复编译问题。如果修复两轮仍然不通过，停止并上报。
3. **原有测试回归**：你的修改导致已有测试失败时，立即回退该修改并上报冲突原因。不允许删除或跳过已有测试来通过验证。
4. **合约冲突**：发现已有的公共路由名称需要改变请求或响应结构时，停止并上报，这些是冻结合约。
5. **上游依赖不可控**：需要修改其他服务的接口才能完成本轮任务时，停止并上报为跨服务合约变更。
6. **循环失败**：同一问题修复超过 3 次仍然不通过时，停止并上报问题本身，不要继续尝试。

### 必须停止并输出交付物的情况

7. **全部 P1-P3 完成**：所有优先级任务完成且验证通过后，停止编码，输出完整的交付物（变更总结 + 完成度表格 + 验证结果 + 已知限制）。
8. **部分完成但无法继续**：如果某个优先级任务因外部原因无法完成，标记为 blocked，继续完成其他任务，最终交付时明确标注哪些已完成、哪些被阻塞及原因。

### 不允许的行为

- 不允许跳过验证命令直接报告"完成"
- 不允许用 `# type: ignore` 或 `noqa` 掩盖真实的类型或逻辑错误（已有合理标注的除外）
- 不允许在测试失败时删除或注释掉测试
- 不允许引入破坏性变更后不运行回归测试
- 不允许在遇到阻塞时静默继续下一个任务而不记录

### 上报格式

遇到需要上报的情况时，输出以下格式：

```
## BLOCKER REPORT
- 类型：[code | environment | dependency | contract | upstream]
- 服务：auth-user-service
- 问题描述：（一句话描述）
- 错误信息：（原始错误或日志）
- 已尝试修复：（列出已尝试的方案）
- 需要的下一步动作：（需要谁做什么）
- 当前完成状态：（已完成哪些 P 任务、哪些被阻塞）
```
