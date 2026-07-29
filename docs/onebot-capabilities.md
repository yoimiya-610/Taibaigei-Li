# OneBot 最低能力与可选增强能力

李太白给通过 OneBot V11 适配器接入协议端。连接成功后，机器人只调用
`get_version_info` 和 `get_status` 两个只读标准 API，登记实现名称、实现版本、
连接健康度和能力状态；不会为了探测而发送消息、点赞、戳一戳、修改精华消息或
群设置。

能力状态含义：

| 状态 | 含义 |
| --- | --- |
| `supported` | OneBot 标准、已识别实现的官方声明或真实业务成功调用表明可用。 |
| `unsupported` | 已识别的普通 OneBot 实现不声明该扩展，或真实业务调用明确返回不支持。 |
| `unknown` | 当前没有无副作用的判断依据；不会因此把实现猜成 NapCat。 |
| `degraded` | 连接、只读探测或该能力最近一次真实业务调用异常，可在后续连接或调用中恢复。 |

## 最低能力

部署至少需要可连接的 OneBot V11 实现，并支持收发机器人现有业务消息。能力注册表
把下列现有调用按 OneBot V11 标准能力处理：

| 功能 | OneBot API | 降级方式 |
| --- | --- | --- |
| 名片点赞 | `send_like` | 仅点赞功能失败或关闭，其他命令继续运行。 |
| 图片地址刷新 | `get_image` | 无可用刷新结果时，图片业务应回退到消息段原有地址或文件信息。 |

OneBot V11 规范列出了 `send_like`、`get_image`、`get_status` 与
`get_version_info`。因此，即使实现名称无法识别，标准能力仍按协议运行；只有真实
业务结果才能把对应能力更新为 `unsupported` 或 `degraded`。

## 可选增强能力

| 功能 | API | 普通 OneBot | NapCat |
| --- | --- | --- | --- |
| 群戳一戳 | `group_poke` | `unsupported` 或 `unknown` | 官方声明支持 |
| 精华消息 | `get_essence_msg_list`、`set_essence_msg`、`delete_essence_msg` | `unsupported` 或 `unknown` | 官方声明支持 |
| 图片 OCR | `ocr_image` / `.ocr_image` | `unsupported` 或 `unknown` | 官方声明支持 |

这些增强能力不属于机器人整体启动条件。某一项缺失、超时或返回异常时，只更新这一项
的状态；共享调用接口不会把其他能力或整个 OneBot 连接一并判为不可用。

## 实现识别与重连

- `app_name` 明确识别为 NapCat 时，按 NapCat 官方兼容声明登记增强能力。
- 明确返回通用 OneBot 实现名时，标准能力为 `supported`，扩展能力为
  `unsupported`。
- 其他实现只登记经过安全过滤的名称和版本；标准能力为 `supported`，扩展能力保持
  `unknown`。
- 断线时连接状态变为 `disconnected`，已知可用能力暂记为 `degraded`；重连后重新执行
  只读探测并替换旧连接状态。

实现名称、版本和能力状态只保存在进程内存中，不写入运行数据。管理员可使用
`/系统诊断` 查看脱敏摘要；输出不包含 access token、WebSocket 地址、账号、群号或
原始 API 响应。

参考：

- [OneBot V11 公开 API 规范](https://github.com/botuniverse/onebot-11/blob/master/api/public.md)
- [NapCat OneBot API 兼容情况](https://napneko.github.io/develop/api)
- [NapCat 扩展 API](https://napneko.github.io/develop/api/doc)
