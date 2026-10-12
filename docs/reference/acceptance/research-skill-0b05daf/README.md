# 研究 skill 固定候选的独立原件

[原报告](capture/report.md)逐字归档，SHA256 `cc9b5a6d5b844d2f11983340f1d1859364388b3c4fa03e384f0c20774b65f683`。其限定 PASS 仅证明 `0b05daf92c8478f990af46e6edf45a6b10abb60f` 与报告列出的隔离 CLI/HTTP/fixture 场景，不证明本轮额度维护代码、真实 Harbor/Hub/Docker/LLM 效果或生产部署。

`capture/` 保全原 CLI stdout/stderr/退出码、202 后代理504、请求、结果、收尾及原16项摘要索引；`early-fixtures/` 保全早期夹具失败的非秘密输出。源 capture 不含 PAT 原值；本次另扫描 PAT 形态，无命中。未复制 state、外置 master、PAT/profile、完整资源或 harness。逐字源路径/字节数/摘要由 [archive-sha256.json](archive-sha256.json) 固定；原 SHA256SUMS 是源 capture 的索引，不是本轮新增归档索引。
