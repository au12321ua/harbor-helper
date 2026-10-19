# 浏览器 HTTP 类型契约

后端公开 DTO 是字段来源：`service/dtos.py` 定义机器传输及共享模型，`service/browser_contracts.py` 定义浏览器 DTO 与契约注册表，复用这些共享模型和 `service/attachment_contracts.py` 的附件模型。`service/machine.py` 负责机器运行时投影；机器 schema 路由与装配在 `service/http/machine.py`，引用 `dtos.py` 的传输模型。`persistence/statuses.py` 定义运行、提交、审计和报告状态；执行写入和浏览器 DTO 引用同一来源，不改变状态转换。

在仓库根目录执行：

```bash
uv sync --locked --group dev
uv run python tools/browser_contract.py
uv run python tools/browser_contract.py --check
cd frontend
npm ci
npm run test:types
npm run build
npm run lint
```

生成文件为 `frontend/contracts.json` 和 `frontend/src/generated/contracts.ts`，两者入库。工具使用项目锁定的 Python/Pydantic/FastAPI，不依赖外部生成服务或新依赖。修改 DTO 或路由后先更新生成物，再修改消费代码；`--check` 对缺失或漂移的文件失败。生成器遇到不支持的 JSON Schema 形式会失败，显式开放 JSON 才生成 `unknown`。输出路径可用 `--output`、`--schema-output` 指定。

导出不接受运行 root，不启动 app lifespan、HTTP、scheduler 或外部执行。路由枚举使用自有临时目录中的未初始化 app，临时文件自动删除；不读取已有 state、用户配置或秘密。只导出登记的浏览器契约，不发布管理员 OpenAPI，不改变 `/api/v1/machine/schema` 的 allowlist。

`ContractRoute` 在 FastAPI 序列化之前验证 handler 原始输出，递归拒绝 DTO 未声明键、缺失必需字段、错误类型和非法状态；显式 JSON 映射保持开放。校验结果不用于补默认值或删除原始字段。响应缺陷返回安全 `503 service_unavailable`，不进入请求的 422 分支，也不回显输入。浏览器与 PAT 按已认证 actor 选择独立模型；原机器 Accepted 的 schema 保持不变，输出在验证后直接发送，防止其过滤浏览器诊断列表。

管理写入使用独立 schema 描述，实际接受集合、空/null/缺省处理和业务错误由 handler 与业务验证器决定。配置中允许的任意 JSON 标签、参数和 falsy 默认引用继续保留，前端先收窄或转为显示文本；不以响应模型变相收紧写入。

页面使用 `api`、`post`、`mutation`、`upload`。泛型只能由生成的方法/路径推导，调用方不能指定任意响应 DTO。动态路径按后端路由逐段匹配，再优先选择较具体路由；普通参数仅消费一段，拼错的 `/runs/id/logz` 不会被详情 ID 吞掉，`{key:path}` 则保留跨段查询。动态字符串 ID 的实际内容仍须符合服务器参数规则，编译器不证明运行时字符串值。`mutation` 只有 POST 可省略方法，PATCH/PUT 必须传入相符的运行时方法；页面转发封装沿用同一约束。JSON 请求体直接传对象；附件 `upload` 将生成的 metadata DTO 编码为 multipart JSON 字符串、接收 File/Blob，要求稳定幂等键，页面保留失败后的重试键。同源 cookie、请求头和 session-expired 行为保留。

`frontend/type-tests/contracts.ts` 使用实际调用层验证字段、方法、body、HTTP 路径、状态、nullable、附件 metadata/文件/幂等键和穷尽标签表的负例，不进入生产 bundle。新增状态会使标签表缺项报错，运行时未知标签仍回显原值。

## 契约覆盖

完整方法、路径、输入和响应以入库的 [contracts.json](../../frontend/contracts.json) 及 [生成类型](../../frontend/src/generated/contracts.ts) 为准，执行 `tools/browser_contract.py --check` 核对源码与生成物。这里不另维护一份容易过时的路由表。

生成契约覆盖账户/PAT、管理员配置与数据集操作、主密钥、维护与更新、附件、实验受理/详情/日志/报告/比较及产物入口。浏览器与 PAT 的共享路径分别校验其投影；动态 path/query 和 JSON 输入按注册契约约束。附件使用 multipart，下载保留导航传输及原权限/审计门禁。机器专用 API、SPA fallback 与静态资源不进入浏览器类型导出。

## 路由全集闭合

HTTP 装配只接受精确 `ContractRoute` 和登记的可选 `/assets` 包内 `StaticFiles` 挂载。每条 HTTP 路由在构造时分类，装配末尾再穷尽检查 `app.routes`；include_router 包装、子应用 Mount、WebSocket、普通 Route/APIRoute 和意外子类均会明确失败。将来改变扁平装配方式时须同步更新边界和逃逸测试。

浏览器路由必须有 BROWSER 登记、`/api/v1/` 前缀、单一方法和原始输出校验包装。非浏览器 HTTP 入口只能匹配 `service/route_contracts.py` 中带原因的精确豁免：方法集、保留转换器的原始路径、handler module/qualname。健康探针、机器投影/schema、二进制下载、favicon 和两个 fallback 是独立豁免；机器前缀不是通用豁免。资产 Mount 可缺席，其余登记必须实际出现。

handler 名字全局唯一；相同方法集和参数名归一化路径不得重复，归一化保留 `:path` 等转换器。BROWSER 与豁免不能重叠或悬空，MACHINE/REQUESTS 必须是 BROWSER 子集，API 404 与 SPA fallback 必须最后注册。检查使用运行时异常，在优化 Python 下仍有效。未知输出模型返回安全 503。

导出消费共享完整分类结果，不再通过 BROWSER 名字过滤实际路由；JSON/TS 生成物的 `--check` 仍负责绑定名字到方法/路径并防止漂移。维护新增路由时同时更新登记、精确豁免（如适用）、生成物和正反例，不以名称或路径前缀绕过检查。
