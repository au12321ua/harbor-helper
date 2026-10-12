# 0.2.0 标识修正安全证据

[补工程报告](engineering-report.md)记录Root确定0.2.0后的版本标识同步、固定2c104ac构建/包内容与CLI入口补验；工程完成待Root/最终Checker。旧8519109报告与352/29及efbc359串联证据不改写、不重跑。

`capture/`逐字保全本轮原命令/环境白名单、stdout/stderr、退出，含检查脚本首次调用方式失败。`SHA256SUMS`是本目录实际索引；metadata另列二进制包摘要。排除state/home/profile/cache/private、截图和包二进制。脚本含本轮专用临时路径；重新执行前须更换独立根，避免覆盖已有证据/解包目录。
