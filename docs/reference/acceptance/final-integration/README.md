# 最终集成工程证据

[工程报告](engineering-report.md)记录固定6db930产品的一轮全量与固定efbc359的完整生产网页/CLI串联，工程完成待Root和Checker；不是正式发布或整个阶段PASS。

`capture/`为白名单原命令/字节输出/退出、CLI原文本记录与请求/结果/teardown，包含首轮定位失败。`SHA256SUMS`只索引实际归档文件；`metadata.json`含版本、数量和包摘要。截图/state/home/profile/cache/private/master/PAT原值不入库，完整隔离测试state仅本地供核查。

`drive.py`与`frontend/qa/final-integration-production.mjs`是本轮研究/网页集成验证harness，非服务运行开关。`run.py`/check脚本保全执行方法与白名单前置，含本轮专用临时路径；复跑要使用新的独立根，先检查不会覆盖现存证据或state，不在部署目录执行。检查脚本没有全历史锚点/秘密清除证明。
