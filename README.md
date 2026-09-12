# 189Cloud-Checkin

天翼云盘多账号个人签到脚本，使用 PC 登录流程，支持可选的 Telegram 汇总通知。

唯一程序入口为 `index.py`。旧 WAP 登录脚本和旧调度文件已移除，可从 Git 历史查阅。

## 功能与边界

- 串行处理多个账号，一个账号失败不影响后续账号。
- 区分本次签到成功、今日已签到、失败或结果未知。
- 不执行抽奖或家庭签到，不自动重试签到请求。
- 遇到验证码或设备校验时报告错误，不保证自动恢复。
- 每次运行重新登录；不持久化 Cookie、Session 或 Token。
- Telegram 使用带状态图标、加粗标题与账号的 HTML 报告，动态内容自动转义；未配置或发送失败不改变签到结果。

## Python 与依赖

代码以 Python 3.6 为兼容目标，直接依赖仍为：

```text
requests==2.24.0
rsa==4.7
```

两个版本的包元数据允许 Python 3.6。不要把较新 Python 环境中的依赖直接复制到 Python 3.6 运行时，也不要无版本限制地升级依赖。

`requirements-189Checkin.zip` 是保留的历史依赖包，不包含新版程序，也不是已经重新验证的新版部署包。语法兼容不代表目标云函数环境已验证，部署前仍需使用实际运行时和依赖测试。

在目标兼容环境准备依赖：

```bash
python -m pip install -r requirements.txt
```

## 账号配置

环境变量 `TY_ACCOUNTS` 的内容为 JSON 数组，字段名为 `username`、`password`：

```json
[
  {"username": "YOUR_ACCOUNT_1", "password": "YOUR_PASSWORD_1"},
  {"username": "YOUR_ACCOUNT_2", "password": "YOUR_PASSWORD_2"}
]
```

也可以在私有部署副本中修改 `index.py` 顶部的配置：

```python
accounts = [{"username": "YOUR_ACCOUNT", "password": "YOUR_PASSWORD"}]
```

1. `TY_ACCOUNTS` 存在时，完整替代硬编码账号列表，不与其合并。
2. 环境变量不存在时，才读取硬编码 `accounts`。
3. 环境变量为空、JSON 错误、列表为空或字段不合法时，直接报配置错误，不回退到硬编码账号。
4. 所有账号在发起请求前完成配置校验；密码中的特殊字符及首尾空格不会被自动修改。

公开源码保持 `accounts = []`。真实账号密码只放在云函数环境变量或私有部署副本，不进入 Git、发布包或日志。程序不自动读取 `.env` 文件。

## Telegram（可选）

设置环境变量 `TG_BOT_TOKEN`、`TG_CHAT_ID`；或者在私有副本中填写同名源码配置。

- 任一 Telegram 环境变量存在，就整体使用环境变量这一组，不与源码配置混用。
- 两项均为空：不推送。
- 仅一项非空：提示配置不完整，不推送，但继续签到。
- 两项均非空：签到结束后发送汇总。

通知显示脱敏账号。默认关闭响应摘要日志；即使开启 `PRINT_RESPONSE_BODY`，也只输出白名单业务状态，不输出完整认证响应。

## 运行与云函数入口

本地执行（会真实登录、签到，配置 Telegram 后还会发送通知）：

```bash
python index.py
```

华为云 FunctionGraph 函数入口为 `index.main_handler`。部署包根目录包含 `index.py` 和目标运行时可用的依赖，不包含旧脚本、`local/`、`.env`、测试文件或个人日志。推荐通过环境变量提供凭据，使部署代码本身不含秘密。

函数正常返回的 `statusCode: 200` 表示调用完成，不等于所有账号签到成功。解析 JSON 字符串 `body` 查看：

- `ok`：所有账号是否都签到成功或今日已签到；配置错误时为 `false`。
- `counts`：`signed`、`already_signed`、`failed` 数量。
- `results`：逐账号脱敏结果。
- `notification`：`disabled`、`incomplete`、`sent` 或 `failed`。
- 配置错误时返回 `config_error`，`notification` 为 `not_attempted`，不发起业务请求。

不要仅因业务结果失败就无条件重跑整个批次：网络超时可能发生在服务端已经完成签到之后。

## 离线检查

```bash
python -m unittest discover -s tests -v
```

测试使用模拟请求，不登录真实账号、不签到、不发送通知。线上登录、签到和 Telegram 送达需要分别验证，离线检查不能替代目标 Python 3.6 环境实测。
