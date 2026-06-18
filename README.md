# EasyNovel

一个极简本地长篇小说生成器：配置模型全局 Prompt，填写故事大纲、人物设定、章节目录和写作风格后，后台会逐章调用 OpenAI 兼容接口生成正文，并在每章后检查、修订、更新剧情记忆和人物状态。

## 启动

PowerShell:

```powershell
python app.py
```

然后打开：

```text
http://127.0.0.1:8000
```

进入页面后点右上角 `配置 API`，在配置页里新增模型配置：

- `Chat Completions`：OpenAI 兼容 `/chat/completions` 接口
- `Responses`：OpenAI 兼容 `/responses` 接口
- `Anthropic / Authpic`：Anthropic Claude 风格 `/messages` 接口，使用 `x-api-key` 和 `anthropic-version` 请求头

配置页支持填写全局 Prompt、测试连接、获取模型、设置推理深度。保存后回到主页面，在 `模型配置` 下拉框里选择要使用的配置再开始生成。

主页面提供 `AI 设定助手`，可以先和 AI 描述小说想法，让它生成故事大纲、人物设定、章节目录和写作风格，再一键导入到设定页。

API Key 会保存在浏览器本地存储，方便自用场景反复使用；不会写入 `input/` 文件，也不会进入生成的小说文件。不要把浏览器本地存储或截图发给别人。

## 本地测试模式

不想真的调用 AI 时，可以用模拟模式检查流程：

```powershell
$env:NOVEL_MOCK="1"
python app.py
```

## 文件说明

- `input/outline.txt`：故事大纲
- `input/characters.txt`：人物设定
- `input/chapters.txt`：章节目录和每章要求
- `input/style.txt`：写作风格
- `memory/summary.txt`：自动生成的前文记忆
- `memory/character-state.txt`：自动生成的人物状态
- `output/chapter-001.md`：单章输出
- `output/novel.md`：整本小说输出

生成时默认会额外携带最近 3 章正文，配合全书摘要和人物状态一起维持连贯性。

主页面的生成参数会保存在浏览器本地存储中；每章目标字数上限为 20000，可点击 `最大` 一键填入。

## 章节目录写法

推荐每章写清楚必须事件和禁止事项：

```text
第1章：雨夜来信
必须写：林舟收到母亲失踪前留下的信，决定回到旧城。
不能写：不能揭露母亲失踪真相。
```
