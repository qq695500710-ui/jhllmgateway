# jh_build_jianhuallm

## 项目简介
一个本地 AI 兼容网关项目，用于把多种模型服务统一包装成 OpenAI 兼容接口，方便桌面工具、脚本和扩展直接调用。

## 原始功能
- 提供本地 HTTP 接口，统一暴露 chat、embedding、responses 等能力。`r`n- 支持将请求路由到不同上游模型服务。`r`n- 可作为本地代理层承接桌面工具与浏览器扩展请求。

## 二次开发功能
- 增加了本地打包、托盘化与更贴近桌面分发的运行方式。`r`n- 增加了更细的超时、重试和路由配置。`r`n- 用于给文章分发、内容改写等项目提供统一 AI 后端。

## 运行方式
```powershell`r
python -m venv .venv`r
.\.venv\Scripts\activate`r
python -m pip install -r requirements.txt`r
python server.py --config peizhi.json`r
```

## 使用与署名
- 使用、分发或二次开发本项目时，请保留原仓库中的署名说明。
- 允许在保留署名的前提下进行二次开发、修改和再发布。
- 本仓库默认用于学习、测试、研究与演示，不建议直接商用。
- 使用者应自行评估部署、数据、平台规则与当地合规要求；因违规使用产生的后果由使用者自行承担。
