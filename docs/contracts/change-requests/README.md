# Change Requests

非 foundation 工作流如果发现公共 contract / schema / OpenAPI / 配置规范存在缺口，必须在本目录提交变更申请。

请复制 `CHANGE_REQUEST_TEMPLATE.md` 新建申请文件，文件名建议使用：
- `YYYYMMDD-<supervisor>-<topic>.md`

最少需要说明：
- 背景
- 当前缺口
- 建议变更
- 影响范围
- 兼容性说明
- 是否阻塞当前工作流

foundation 在处理完成后，申请文件必须追加 `Foundation Processing Result` 或 `Foundation 处理结果` 段落；当前 root-level foundation validator 会把未标记结果的申请视为未完成。
