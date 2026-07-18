## jianhuallm.exe 的调用文档（给其它 EXE / Web / 扩展调用）

作者：程序员小玖微信:YOUR_CONTACT TG: your_contact  
版权：2014-2026  
描述：网站开发定制、脚本定制、反向编程、支付对接等

---

### 1）它是什么（你要的小白可用“统一 AI 网关 EXE”）

`jianhuallm.exe` 启动后会在本机固定端口 **10830** 提供一套 **OpenAI 兼容** 的 HTTP 接口。  
其它程序（浏览器扩展、网页后端、其它 exe）只需要像调用 OpenAI 一样调用它即可。

- **固定地址**：`http://127.0.0.1:10830`
- **固定端口**：**10830**（不会随机变化，便于被其它程序长期稳定调用）
- **上游配置**：与 exe 同目录的 `peizhi.json`（上游模型 / API Base / API Key）

---

### 2）准备工作（必须做一次）

把这两个文件放在同一个目录（同级）：

- `jianhuallm.exe`
- `peizhi.json`

然后编辑 `peizhi.json`，把你实际的上游 `api_base` / `api_key` 填进去。

---

### 3）启动方式

#### 方式 A：双击启动（最适合小白）

直接双击 `jianhuallm.exe`，它会在 **Windows 右下角托盘**出现图标并后台运行网关（关闭托盘图标才算退出）。

#### 方式 B：命令行启动（便于看日志）

```powershell
cd "C:\路径\到\jianhuallm"
.\jianhuallm.exe
```

指定配置文件（可选）：

```powershell
.\jianhuallm.exe --config ".\peizhi.json"
```

---

### 4）网关鉴权说明

当前版本 **不在本地网关层做 API Key 校验**（其它程序可直接调用 `http://127.0.0.1:10830/...`，无需带 `Authorization` / `x-api-key`）。  
上游密钥仍在 `peizhi.json` 的 `upstreams.*.api_key` 中配置，由网关转发给上游。  
若你需要“只允许本机部分程序访问”，请用 **Windows 防火墙 / 反向代理 / 独立鉴权网关** 在更外层实现。

---

### 5）接口清单（OpenAI 兼容）

- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `POST /v1/responses`（含 stream）
- `GET/POST/DELETE /v1/files`（含 `GET /v1/files/{id}/content`）
- `POST /v1/images/generations`
- `POST /v1/audio/transcriptions`
- `POST /v1/audio/speech`（返回二进制音频）
- `GET/POST /v1/batches`、`GET /v1/batches/{id}`、`POST /v1/batches/{id}/cancel`

---

### 6）其它程序调用会不会出现“乱码”？（结论 + 分类）

这里的“乱码”分三类，**不要混为一谈**：

| 场景 | 会不会乱码 | 说明 |
|---|---|---|
| **HTTP 请求 JSON（UTF-8）→ 网关** | 正常不应乱码 | 你的程序必须用 **UTF-8** 生成 JSON 字节流；`Content-Type` 建议带 **`charset=utf-8`**。不要把 JSON 用系统 ANSI/GBK 另存成“看起来像 json 的乱码文件”。 |
| **HTTP 响应 JSON（UTF-8）→ 你的程序** | 正常不应乱码 | 网关已统一返回 **`Content-Type: application/json; charset=utf-8`**。你的程序应用 **UTF-8** 解码响应体再 `JSON.parse`/反序列化。 |
| **控制台/终端 `print` 中文** | **可能**“看起来像乱码” | 这是 **显示层编码**问题（尤其 Windows PowerShell 5.x + 旧控制台），**不代表** HTTP 传输出错。业务程序 UI/日志文件一般不受此影响。 |

**反方提醒（挑战视角）**：如果你把网关放在公网或反向代理后面，中间层若错误转码/压缩/篡改 `Content-Type`，仍可能导致客户端误判编码——所以生产环境要关注 **代理是否剥离 charset**。

---

### 7）全程序统一调用方式（唯一推荐：不限制正文长度）

**核心原则（所有语言通用）**：

1. **不要把超长 JSON 拼进命令行**（`cmd` / `PowerShell` 都有长度与转义限制，且容易截断/断义）。
2. 统一改为：**先把完整请求体写入一个 UTF-8 的 `request.json` 文件**（或由程序在内存中构造 JSON 字节数组），再用 HTTP 客户端 **POST 原始字节**到对应路径。
3. 请求头固定带：`Content-Type: application/json; charset=utf-8`（若开启鉴权再加 `Authorization` / `x-api-key`）。
4. 响应体用 **UTF-8** 解码后再解析 JSON；需要落盘排查时用 **UTF-8** 写文件。

下面给出 **唯一** 的“手工验证/脚本联调”示例（与业务语言无关：任何程序只要能发 HTTP，就照 **“读 UTF-8 文件 → POST → 写 UTF-8 文件”** 做即可）。

#### 7.1 准备 `request.json`（UTF-8，内容可任意长）

示例（你可把 `messages[0].content` 换成整篇文章）：

```json
{
  "model": "smart",
  "messages": [
    { "role": "user", "content": "你好" }
  ]
}
```

#### 7.2 发送请求并把响应写入 `response.json`（无命令行长度限制）

在 **cmd.exe** 或 **PowerShell** 中都可运行（注意：把 `request.json` / `response.json` 的路径改成你的真实路径）：

```bat
curl.exe -s -S -X POST "http://127.0.0.1:10830/v1/chat/completions" -H "Content-Type: application/json; charset=utf-8" --data-binary "@request.json" -o response.json
```

#### 7.3 你的业务程序怎么“对齐”这个唯一方式（不写多种命令）

- **C# / Java / Go / Rust / Node / Python / 浏览器 fetch**：都用各自 HTTP 库构造 **UTF-8 字节**的 body（来自 **文件** 或 **内存**），不要走“超长命令行拼接 JSON”。
- **浏览器扩展 / 网页**：用 `fetch`/`axios` 直接 `JSON.stringify` 对象后 POST（浏览器默认 UTF-8），长文本放在对象字段里即可。
- **另一个 EXE**：同理，**从文件读入请求体**或从 UI/数据库读到内存再 POST。

---

### 8）补充：流式 SSE / 二进制响应

- **SSE 流式**：仍建议由程序用 HTTP 客户端读 **流**（不要试图用“单行命令行”承载无限长度）。
- **`/v1/audio/speech`**：响应是二进制，请用客户端保存为 `.mp3/.wav` 等文件，不要当 JSON 解析。

---

### 9）托盘“设置AI”怎么用（无需网页）

在 Windows 右下角托盘图标上 **右键**：

- 点击 **`设置AI`**：会弹出一个窗口，直接编辑 `peizhi.json`（JSON 文本）。  
  - 点 **保存**：会写回 `peizhi.json`。  
  - 本网关会在每次请求时读取最新配置，因此一般 **无需重启**。
- 点击 **`退出`**：关闭网关。

作者：程序员小玖微信:YOUR_CONTACT TG: your_contact  
版权：2014-2026  
描述：网站开发定制、脚本定制、反向编程、支付对接等


