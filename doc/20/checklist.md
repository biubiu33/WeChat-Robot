# 微信群聊 @ 触发与按成员批处理 Checklist

状态：已完成（自动化验收通过）

> 以下项目已通过自动化测试、构建检查、代码检查或只读 UIA 探测验证；未向真实群聊发送测试消息。

## Configuration

- [x] `allowed_groups` 与 `self_names` 均解析为去重后的精确字符串元组。（verification：配置参数化测试）
- [x] 示例配置包含 `测试群聊` 与 `biubiubiu仿生人`。（verification：README 和 example 搜索）
- [x] 私聊或群聊至少一个白名单非空即可启用；两者都为空时明确失败。（verification：配置正反测试）
- [x] 配置群聊但没有 `self_names` 时明确失败。（verification：配置负向测试）
- [x] 私聊与群聊白名单同名、列表内重复或空项时明确失败。（verification：配置负向测试）
- [x] `allowed_groups=[]` 时不构造或预热 OCR，现有私聊行为不变。（verification：CLI/driver mock 测试）

## Startup Baseline And Discovery

- [x] 启动时主动为白名单群建立消息基线，不产生旧消息事件。（verification：driver baseline 测试）
- [x] 基线中的旧 @ 不触发、不入待处理批次、不进入 20 条上下文。（verification：driver + bot 集成测试）
- [x] 会话行能够识别 `[有人@我]` 与兼容标记并用于优先扫描，但不会仅凭标记选中具体消息。（verification：解析和负向触发测试）
- [x] 机器人停留在活动群时，即使会话行没有 @ 标记，新气泡正文精确 @ 仍能触发。（verification：活动群消息测试）
- [x] 当前标题与成员数共同确认群类型，私聊/群聊候选类型不符时拒绝。（verification：UIA client mock 测试）
- [x] 搜索结果不唯一、标题不一致或群成员数不可确认时不读取、不发送。（verification：UIA client 负向测试）
- [x] 微信 `4.0.5.15`、`4.1.9.30` 和 `mmui::MainWindow` 支持列表未回归。（verification：常量与现有版本测试）
- [x] UIA 未激活时仍提示“请先启动 Windows 讲述人并重启微信”，程序不操作讲述人。（verification：现有错误路径测试）

## Message Identity And OCR

- [x] 消息正文始终来自 UIA，OCR 结果不会覆盖正文。（verification：OCR 赋值测试）
- [x] 可见文字消息记录 runtime id、边界、方向与发送者状态。（verification：UIA message parser 测试）
- [x] runtime id 缺失时有稳定哈希回退，相同可见消息重复扫描只产生一次。（verification：driver snapshot 测试）
- [x] RapidOCR 只在本机内存处理聊天区域截图，代码不保存截图文件。（verification：代码检查与 mock ImageGrab 测试）
- [x] OCR 正文通过文字相似度和几何位置唯一关联 UIA 气泡。（verification：纯函数测试）
- [x] 昵称必须位于气泡上方、水平对齐、唯一且达到置信阈值。（verification：成功与边界测试）
- [x] 低置信、正文不匹配、多个昵称、昵称缺失和引擎异常全部返回未知。（verification：参数化负向测试）
- [x] 未知发送者消息既不入群上下文，也不触发批次。（verification：driver + bot 测试）
- [x] 群聊配置启用但 OCR 依赖或引擎不可用时在监听前明确失败。（verification：CLI 预热失败测试）

## Mention Trigger

- [x] 机器人名称做 NFKC 规范化并兼容 `\u2005`、`\u00a0`。（verification：mention 参数化测试）
- [x] 只有完整 `@biubiubiu仿生人` 命中，子串或模糊名称不命中。（verification：mention 负向测试）
- [x] 群白名单、具体正文 @、入站文字和已知发送者四项缺一均不触发。（verification：组合参数化测试）
- [x] 送入当前问题前移除机器人 @ 及相邻空白。（verification：runtime 输入断言）
- [x] 对其他群成员的 @ 保持原样。（verification：多 @ 文本测试）
- [x] 图片、文件、语音、视频、分享卡片与纯引用均不触发。（verification：message kind 参数化测试）

## Per-Sender Quiet Windows

- [x] 群批次键为 `(conversation_name, sender_name)`，私聊批次键保持原语义。（verification：bot 状态测试）
- [x] 张三与李四交叉 @ 时分别建立窗口，不合并事件。（verification：受控时钟测试）
- [x] 张三的新 @ 只重置张三的 7 秒计时，不修改李四 deadline。（verification：受控时钟测试）
- [x] 张三未 @ 的补充消息不进入张三活动批次。（verification：批次内容断言）
- [x] 同一成员多条且每条都 @ 的消息按观察顺序合并为一次模型调用。（verification：queue 消费测试）
- [x] 到期批次按到期顺序进入全局 FIFO。（verification：多个 timer 测试）
- [x] 群新 @ 不取消正在生成或发送的群回复，只创建新窗口。（verification：cancel event 断言）
- [x] 私聊同好友新消息仍取消现有私聊回答。（verification：现有私聊取消回归）
- [x] 关闭机器人会取消全部按成员 timer 并安全清空状态。（verification：stop 测试）

## Shared Group Context

- [x] 每群使用独立 `deque(maxlen=20)`，不同群上下文不混合。（verification：多群 bot 测试）
- [x] 已知发送者的启动后普通文字可进入参考上下文，但不会触发模型。（verification：上下文与调用次数断言）
- [x] 第 21 条可信消息到来后最早一条被删除，顺序保持正确。（verification：边界测试）
- [x] 每条上下文包含发送者昵称和未经 OCR 改写的 UIA 正文。（verification：冻结快照断言）
- [x] 队列入队时冻结上下文，后续消息不会修改已排队批次的快照。（verification：不可变快照测试）
- [x] 模型输入明确区分“不可信参考记录”和“当前需要回答的 @ 消息”。（verification：provider 请求断言）
- [x] 当前问题只包含一个发送者的合格消息，不同成员不会混入。（verification：交叉批次 runtime 测试）
- [x] 群模型调用不恢复旧群 Session，启动前历史不会重新进入上下文。（verification：预置 archive 负向测试）
- [x] 私聊仍恢复并持久化各好友 Session。（verification：现有 runtime 回归）
- [x] `role.md`、`reply_policy.md` 和原始最终回复控制台打印继续生效。（verification：提示词与 stdout 回归测试）

## Real Mention And Text Fallback

- [x] 仅群回复第一条气泡尝试真正 @。（verification：bot send call sequence）
- [x] 输入 `@` 后只选择当前微信窗口内唯一、昵称精确相等的成员候选。（verification：UIA mock 成功测试）
- [x] 真正 @ 前后都复核目标群名与群类型。（verification：target change 测试）
- [x] 菜单未出现、超时、无匹配或多匹配时关闭弹层并清理本次草稿。（verification：四条降级测试）
- [x] 降级发送格式为普通文本 `@发送者昵称` 加第一条正文。（verification：发送参数断言）
- [x] 降级日志包含群名、发送者和原因，不包含消息正文。（verification：日志捕获断言）
- [x] 降级不重新调用模型、不重试真实 @、不重复发送第一条气泡。（verification：调用次数断言）
- [x] 后续聊天气泡和来源消息不重复 @。（verification：多气泡与来源发送序列）
- [x] 输入框原本非空、清理无法确认或目标变化时安全拒绝，不覆盖用户草稿。（verification：负向 UIA 测试）

## Integration And Safety

- [x] 群与私聊共用一个全局 FIFO 和一个 UIA 临界区，不并发操作微信窗口。（verification：并发测试与代码检查）
- [x] 同名会话或成员无法唯一确认时 fail closed，不使用坐标盲点。（verification：负向测试）
- [x] 群 OCR 截图、20 条上下文和发送者识别结果不写入新数据库表或远端日志。（verification：schema/diff 检查）
- [x] 群聊仍无 Bash、文件、MCP、Skills、Sub-agent、Hook 或长期记忆权限。（verification：system/environment 和 registry 测试）
- [x] 信息工具启用时仅保留现有三个只读公共信息工具。（verification：群 runtime 工具策略测试）
- [x] 未实现历史滚动读取和群总结 Tool。（verification：file/diff 与接口检查）
- [x] 用户已有 `role.md`、`reply_policy.md`、原始回复日志及未提交修改未被覆盖。（verification：最终 diff 对照）

## Build And Tests

- [x] 修改后的微信包可编译。（verification：`python -m compileall src/mewcode/wechat`）
- [x] 微信源文件和测试通过 Ruff 检查。（verification：`python -m ruff check ...`）
- [x] 微信源文件和测试通过格式检查。（verification：`python -m ruff format --check ...`）
- [x] 配置、OCR、UIA、driver、bot、runtime 专项测试通过。（verification：专项 pytest 命令）
- [x] 全量自动化测试通过，或仅存在已记录且与本功能无关的基线失败。（verification：`python -m pytest -q`）
- [x] wheel 包含新增 OCR 模块、两个提示词文件和正确的微信可选依赖元数据。（verification：构建并检查 wheel）
- [x] `git diff --check` 无空白错误，未修改无关依赖或工作区文件。（verification：最终 diff）

## End-To-End Scenarios

- [x] E2E-1：启动时 `测试群聊` 已有旧 @，机器人建立基线后不回复；启动后张三新发 @ 才触发。（verification：模拟 UIA 端到端测试）
- [x] E2E-2：张三和李四交叉发送两条 @，各自 7 秒合并、形成两个 FIFO 模型请求且互不取消。（verification：bot/runtime 集成测试）
- [x] E2E-3：张三在活动窗口发送普通补充消息，该消息只进入群参考上下文，不进入当前提问批次。（verification：批次与 provider 输入对照）
- [x] E2E-4：OCR 无法唯一识别张三时，即使正文包含机器人 @ 也不调用模型。（verification：driver 到 runtime 调用次数）
- [x] E2E-5：模型返回三气泡，第一条真正 @ 张三，后两条不 @；成员菜单失败时第一条仅文本降级一次。（verification：两种发送序列测试）
- [x] E2E-6：模型回答张三期间李四新 @，张三回答完整发送后再处理李四。（verification：全局 FIFO 测试）
- [x] E2E-7：群上下文达到 21 条后，模型只收到最新 20 条且说话人顺序正确。（verification：provider 请求快照）
- [x] E2E-8：非白名单群、无 @、附件、未知发送者、同名搜索结果和目标类型变化均不发送。（verification：安全矩阵测试）
- [x] E2E-9：私聊的新消息取消、持久化 Session、双版本探测和讲述人提示保持现有行为。（verification：私聊/版本回归套件）

## Acceptance Evidence

- 2026-08-21：实际配置解析通过，精确白名单为“测试群聊”，机器人名称为“biubiubiu仿生人”。
- 2026-08-21：RapidOCR/ONNX Runtime 三个模型实际预加载成功，耗时约 2.4 秒。
- 2026-08-21：当前微信 4.1.9.30 只读探测成功，主窗口类为 `mmui::MainWindow`，会话列表、消息列表和输入框均可由 UIA 定位。
- 2026-08-21：`python -m pytest -q`：419 passed，1 skipped。
- 2026-08-21：本次 13 个微信源文件/测试通过 Ruff 规则和格式检查；微信包通过 compileall。
- 2026-08-21：sdist 与 wheel 构建成功；wheel 包含群昵称 OCR 模块、`role.md`、`reply_policy.md` 和正确的 OCR 可选依赖元数据。
- 2026-08-21：`git diff --check` 无空白错误。真实群成员菜单选择与发信未执行，以避免未经授权向外部群聊发送测试消息。
- 2026-08-21：现场复现群搜索按 Enter 后仍停留在原私聊；改为点击唯一群 UIA 会话行/搜索结果后，私聊 → 测试群切换成功。
- 2026-08-21：现场验证微信最小化后，发送前聚焦会先恢复窗口；群切换完成后窗口非最小化且微信进程保持前台。
- 2026-08-21：修复 @ 降级清理发送全局 `Esc` 导致微信隐藏/最小化；清理现在只使用输入框 ValuePattern，测试明确断言降级路径不发送 `Esc`。
- 2026-08-21：真实发送测试确认微信富文本 @ 不会出现在输入框 ValuePattern 中；删除“ValuePattern 必须包含昵称”的错误校验，并增加富文本 @ 不可见的回归场景。
- 2026-08-21：修复后在白名单测试群现场发送“@biubiubiu 你好”，返回 `real_mention=true`，未走文本降级。
