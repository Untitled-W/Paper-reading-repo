---
name: arxiv-survey-refresh
description: 标准 arXiv 综述入库流程。用户提供 arXiv ID 和"入库"指令 → Agent 执行完整五步流程：下载、解析、填写简写、构建 Overlay PDF、登记入库。**核心是 Step 3 必须由 Agent/大模型逐条人工填写所有参考文献的简称，不能转交给用户，也不能交给批量自动脚本生成。**
---
# arXiv 综述入库标准化流程

## 核心作用与场景

**本 Skill 的作用**：将一篇 arXiv 综述论文完整、规范地摄入您的知识库。

**标准触发场景**：
- **用户输入**：提供一个 arXiv ID（如 `2405.03520` 或 `arxiv:2405.03520`）并附加"请入库"等指令。
- **Agent 回应**：执行从下载、加工、到登记索引的**端到端五步流程**，交付一篇带有引用色块的 Overlay PDF 并更新知识库。

**输出定义**：一次成功的"入库"意味着：
1.  **Overlay PDF 生成**：成功构建出带有彩色引用方框的 `<arxiv_id>_overlay.pdf`。
2.  **物理文件**：PDF 和源码已下载到规范目录。
3.  **语义加工**：所有参考文献被赋予有意义的简称。
4.  **知识库集成**：论文信息被登记到知识库数据库。

## 整体工作流（五步流水线）

```
[用户输入 arXiv ID]
        ↓
    Step 1: Materialize
    （创建目录，下载 PDF 和 LaTeX 源码）
        ↓
    Step 2: Emit Template
    （解析参考文献，生成待填简称清单）
        ↓
    Step 3: Fill Short Labels
    （⚠️ 必须由 Agent/大模型逐条人工填写所有参考文献简称）
        ↓
    Step 4: Overlay Build
    （复用已下载源码，构建引用色块 PDF）
        ↓
    Step 5: Ledger & Index
    （登记到论文库，刷新全局索引）
        ↓
[交付：Overlay PDF + 库表更新]
```

---

## 步骤 1: Materialize（物料化）

**目标**：从 arXiv 下载论文的 PDF 和 LaTeX 源码，创建规范的文件结构。

**工作流程**：分三个子步骤执行

### 子步骤 1.1: 获取元数据（创建目录结构）

**脚本**: `scripts/step1_1_fetch_metadata.py`

**预期行为**：
- 调用 arXiv API 查询论文信息
- 获取论文标题、作者、摘要
- 基于标题生成 URL 友好的 slug
- 创建空的目录结构

**命令**：
```bash
python scripts/step1_1_fetch_metadata.py 2405.03520 --vault-root /path/to/vault
```

**参数说明**：
- `arxiv_id`：arXiv ID，如 `2405.03520`
- `--vault-root`：**必填**。知识库根目录路径

**输出**：
- 创建目录：`survey_reading/2405.03520-is-sora-world-simulator/`
- 输出论文标题、作者、slug
- 返回具体的目录路径，供后续步骤使用

### 子步骤 1.2: 下载 PDF 文件

**脚本**: `scripts/step1_2_download_pdf.py`

**预期行为**：
- 自动配置网络代理（应当已内置代理7890）
- 下载论文的 PDF 文件
- 保存到指定目录的 `source/<arxiv_id>.pdf`

**命令**：
```bash
python scripts/step1_2_download_pdf.py 2405.03520 --survey-dir survey_reading/2405.03520-is-sora-world-simulator
```

**参数说明**：
- `arxiv_id`：arXiv ID
- `--survey-dir`：**必填**。具体的综述目录路径（由步骤1.1创建）

**⚠️ 编码问题补丁**：
- 如果下载过程中出现**编码相关错误**（如 `UnicodeDecodeError` 等），优先在脚本侧修复，不要把问题抛回给用户。
- 推荐补丁方案：所有 Python 文件读写统一显式指定 `encoding="utf-8"`；所有外部命令输出读取统一采用容错解码（如 `encoding="utf-8", errors="ignore"`），避免 Windows / MiKTeX / GBK 环境下崩溃。

**输出**：
- 保存 PDF 到：`survey_reading/2405.03520-is-sora-world-simulator/source/2405.03520.pdf`
- 输出下载统计：大小、时间、速度

### 子步骤 1.3: 下载 LaTeX 源码

**脚本**: `scripts/step1_3_download_latex.py`

**预期行为**：
- 自动配置网络代理（应当已内置代理7890）
- 下载论文的 LaTeX 源码压缩包
- 解压到指定目录的 `.arxiv_latex_build/latex_arxiv_raw/`

**命令**：
```bash
python scripts/step1_3_download_latex.py 2405.03520 --survey-dir survey_reading/2405.03520-is-sora-world-simulator
```

**参数说明**：
- `arxiv_id`：arXiv ID
- `--survey-dir`：**必填**。具体的综述目录路径（由步骤1.1创建）

**⚠️ 编码问题补丁**：
- 如果下载过程中出现**编码相关错误**（如 `UnicodeDecodeError` 等），优先在脚本侧修复，不要把问题抛回给用户。
- 推荐补丁方案：所有 Python 文件读写统一显式指定 `encoding="utf-8"`；所有外部命令输出读取统一采用容错解码（如 `encoding="utf-8", errors="ignore"`），避免 Windows / MiKTeX / GBK 环境下崩溃。

**输出**：
- 解压 LaTeX 源码到：`survey_reading/2405.03520-is-sora-world-simulator/.arxiv_latex_build/latex_arxiv_raw/`
- 输出下载统计：大小、时间、速度

---

## 步骤 2: Emit Template（生成模板）

**目标**：解析已下载的 LaTeX 源码，生成待填写的参考文献简称模板。

**工作流程**：一步执行
1. 解析 LaTeX 源码中的 `.bib` 文件，提取所有参考文献信息
2. 生成 `citation_semantic_abbrevs.json` 模板文件，留出"cite_short"和"ref_id"两个位置
3. **脚本执行完毕后自动停止，等待 Agent 操作**

**脚本**: `scripts/step2_emit_template.py`

**输出文件结构**：
```json
{
  "goodfellow2014": {                           // BibTeX 引用键
    "bib_title": "Generative Adversarial Nets",  // 原始论文标题（永远保留）
    "cite_short": "",                           // 待step3填写：针对原标题的有意义的、符合领域认知的简称（如这里应填写GAN）
    "ref_id": "",                               // 待step3填写
    "url": "https://arxiv.org/abs/1406.2661",   // arXiv URL（如果存在）
    "eprint": "1406.2661",                      // arXiv eprint ID（如果存在）
    "status": "todo"                            // 状态：todo（未填）/ filled（已填）
  }
}
```

**命令**：
```bash
python scripts/step2_emit_template.py 2405.03520 --survey-dir survey_reading/2405.03520-is-sora-world-simulator
```

**关键命令行参数**：
- `--survey-dir`：**必填**。具体的综述目录路径（由 Step 1.1 创建）


**输出位置**：
- 生成文件：`survey_reading/2405.03520-is-sora-world-simulator/citation_semantic_abbrevs.json`
- 统计信息：解析的参考文献数量、耗时等

---

## 步骤 3: Fill Short Labels（填写简称）【核心】

**目标**：为综述中的所有参考文献填写有意义的简称，这是生成 Overlay PDF 的前提。

**⚠️ 无脚本步骤 - Agent/大模型人工操作**

**Agent 操作规范**：
0. **责任主体说明**：本步骤中的“人工填写”指由 Agent/大模型亲自阅读每条参考文献并填写，不是要求用户亲自填写。
1. **接收中断**：Step 2 脚本执行完毕后，流程自动停止
2. **打开文件**：找到并打开 `survey_reading/<id>-<slug>/citation_semantic_abbrevs.json`（需要Agent亲自阅读！！！）
3. **逐条填写**：
   - 阅读每个条目的 `bib_title`
   - 理解论文核心内容和领域术语
   - 在 `cite_short` 字段填入有意义简称
   - 在 `ref_id` 字段填入唯一标识（首选arxiv ID，如果没有则使用 bib_title 键）
   - 将 `status` 改为 `"filled"`
4. **验证完成**：确保所有条目的 `status = "filled"` 且 `cite_short` 和 `ref_id` 字段不为空
5. **保存文件**：保存修改后的 JSON 文件
6. **继续流程**：手动运行 Step 4 脚本

**填写要求**：
| 要求 | 正确示例 | 错误示例（禁止） |
|------|---------|-----------------|
| **纯 ASCII** | GAN, Transformer | GAN（生成对抗网络） |
| **有意义缩写** | DDPM, CLIP | Deno Diff Prob Mode |
| **基于知识判断** | Transformer | Attention Is All |
| **长度 ≤ 24 字符** | World Models | A Very Long Survey Title... |


**硬性禁止**：
- ❌ 禁止把 Step 3 转交给用户填写
- ❌ 禁止使用任何自动批量填写脚本直接从标题机械生成简称
- ❌ 禁止机械截断标题前几个词作为简称
- ❌ 禁止在未完成填写时强行继续流程

---

你说得对，我需要修正这几个地方：

## 步骤 4: Overlay Build（构建 PDF）

**目标**：基于已下载的 LaTeX 源码和 Agent 填写的参考文献简称，构建带有彩色引用方框和跳转功能的 Overlay PDF。

**工作流程**：分四个子步骤执行

### 子步骤 4.1: Agent 验证环境准备

**⚠️ Agent/大模型人工操作 - 无脚本步骤**

**预期行为和功能**：
- 验证 Step 3 已完成
- 快速检查本地 LaTeX 环境
- 创建编译工作区

**Agent 操作规范**：

1. **验证 Step 3 完成**：
   ```bash
   # 检查所有参考文献简称已填写
   # 查看 citation_semantic_abbrevs.json
   # 确保所有条目 status = "filled" 且 cite_short 不为空
   ```

2. **快速检查本地 LaTeX 环境**：
   ```bash
   # 快速检查 pdflatex 是否可用
   which pdflatex
   
   # 快速检查 bibtex 是否可用
   which bibtex
   ```

3. **创建编译工作区**：
   ```bash
   # 复制原始 LaTeX 源码到工作区
   cp -r survey_reading/2405.03520-is-sora-world-simulator/.arxiv_latex_build/latex_arxiv_raw/ \
         survey_reading/2405.03520-is-sora-world-simulator/.overlay_build/workdir/
   ```

**验证标准**：
- ✅ 所有参考文献简称已填写
- ✅ pdflatex 和 bibtex 命令可用
- ✅ 工作区创建成功

### 子步骤 4.2: Agent 修改 LaTeX 源码（实现跳转功能）

**⚠️ Agent/大模型人工操作 - 无脚本步骤**

**预期行为和功能**：
- 修改 LaTeX 源码，只实现引用双向跳转功能
- 添加必要的包，建立跳转链接
- **编译测试**，确保修改后能正常编译
- **不修改引用格式**（格式修改留给步骤4.4）

**Agent 操作规范**：

1. **添加必要的包**：
   ```bash
   # 进入工作区
   cd survey_reading/2405.03520-is-sora-world-simulator/.overlay_build/workdir/
   
   # 编辑主 .tex 文件，添加
   \usepackage{hyperref}
   \usepackage[pagebackref]{backref}
   ```

2. **编译测试**：
   ```bash
   # 测试编译，确保没有语法错误
   pdflatex main.tex
   
   # 检查编译是否成功
   if [ -f main.pdf ]; then
       echo "✅ 编译测试通过"
   else
       echo "❌ 编译失败，检查 LaTeX 错误"
   fi
   ```

3. **验证跳转包工作正常**：
   - 查看编译日志，确认没有包冲突
   - 确保 `hyperref` 和 `backref` 包正确加载

**关键点**：
- 此步骤**只添加跳转包**，不修改引用格式
- **必须编译测试**，确保没有语法错误
- 为步骤4.4的格式修改做准备

### 子步骤 4.3: 确定颜色逻辑

**脚本**: `scripts/step4_3_determine_colors.py`

**预期行为和功能**：
- 读取全局缓存 `cite_short_cache.json`
- 检查本地知识库中的文献状态
- 为每篇参考文献分配颜色
- 生成颜色映射文件

**颜色逻辑**：
- **绿色**：本地已下载的文献（存在于 `survey_reading/` 目录中）
- **黄色**：在 `cite_short_cache.json` 中有缓存但未本地下载
- **红色**：完全陌生的文献

**命令**：
```bash
python scripts/step4_3_determine_colors.py 2405.03520 --survey-dir survey_reading/2405.03520-is-sora-world-simulator
```

**输出位置**：
- 颜色映射文件：`survey_reading/2405.03520-is-sora-world-simulator/.overlay_build/color_mapping.json`

**格式示例**：
```json
{
  "goodfellow2014": "citegreen",
  "vaswani2017attention": "citeyellow"
}
```

### 子步骤 4.4: 应用引用格式和颜色

**脚本**: `scripts/step4_4_apply_citation_format.py`

**预期行为和功能**：
- 读取 Step 3 填写的参考文献简称
- 读取步骤4.3生成的颜色映射
- 将 `\cite{key}` 替换为**带背景色**的引用方框
- 在文档头部添加颜色定义
- 执行编译，生成最终 PDF

**颜色定义**：**背景填充色**（不是边框色）
- `citegreen`: 浅绿色背景 `RGB{200,255,200}`
- `citeyellow`: 浅黄色背景 `RGB{255,255,200}`
- `citered`: 浅红色背景 `RGB{255,200,200}`

**工作流程**：
1. 扫描工作区中的所有 `.tex` 文件
2. 查找 `\cite{key}` 命令
3. 将其替换为带背景色的引用框
4. 在文档头部添加颜色定义
5. 执行完整编译流程

**替换示例**：
```latex
% 原始内容
Generative Adversarial Networks (GANs) are important \cite{goodfellow2014}.

% 步骤4.4替换后的内容
% 先添加颜色定义（背景填充色）
\definecolor{citegreen}{RGB}{200,255,200}
\definecolor{citeyellow}{RGB}{255,255,200}
\definecolor{citered}{RGB}{255,200,200}

% 然后替换引用（使用\colorbox设置背景色）
Generative Adversarial Networks (GANs) are important \hyperlink{cite:goodfellow2014}{\colorbox{citegreen}{\textbf{[1:GAN]}}}.
```

**命令**：
```bash
python scripts/step4_4_apply_citation_format.py 2405.03520 --survey-dir survey_reading/2405.03520-is-sora-world-simulator
```

**输出**：
- 修改后的 `.tex` 文件
- 生成的 Overlay PDF：`survey_reading/2405.03520-is-sora-world-simulator/2405.03520_overlay.pdf`
- 编译统计和耗时报告

**关键点**：
- 颜色是**背景填充色**，整个引用框有颜色背景
- 引用框格式：`[数字:简称]` 在彩色背景上
- 必须扫描整个 LaTeX 工作目录中的所有 `.tex` 文件，而不是只修改主文件；很多综述会通过 `\input{sec/...}` 或 `\input{tabel/...}` 分拆正文。
- 如果 `pdflatex` 返回非零，但日志中出现 `Output written on ...` 且目标 PDF 已生成，优先将其识别为 MiKTeX 日志/权限类问题，而不是立即判定构建失败。

---

## 步骤 5: Ledger & Index（登记入库）

**目标**：将已处理的综述论文信息登记到知识库的全局数据库中，包括更新参考文献简称缓存和论文索引。

**工作流程**：分两个子步骤执行

### 子步骤 5.1: 更新参考文献简称缓存

**脚本**: `scripts/step5_1_update_cite_cache.py`

**预期行为和功能**：
- 读取 `citation_semantic_abbrevs.json`
- 将新的参考文献简称添加到全局缓存
- 避免重复添加已存在的条目


**cite_short_cache.json 格式**：
```json
{
  "1406.2661": {                                  // arXiv ID（主键）
    "bib_title": "Generative Adversarial Nets",   // 原始论文标题
    "cite_short": "GAN",                          // 语义简写
    "added_time": "2026-04-29 18:30:00",          // 入库时间（中国时间）
    "added_by_human": false,                       // 是否由 Agent/用户人工添加
    "source_survey": "2405.03520"                 // 首次出现于哪篇综述
  }
}
```

**命令**：
```bash
python scripts/step5_1_update_cite_cache.py 2405.03520 --survey-dir survey_reading/2405.03520-is-sora-world-simulator
```

**参数说明**：
- `arxiv_id`：本篇综述的 arXiv ID
- `--survey-dir`：**必填**。具体的综述目录路径

**输出**：
- 更新 `paper_database/Introduction/cite_short_cache.json`
- 输出添加/更新的参考文献数量统计

### 子步骤 5.2: 登记本综述到索引

**脚本**: `scripts/step5_2_add_to_index.py`

**预期行为和功能**：
- 获取本篇综述的元数据（标题、入库时间等）
- 生成 Markdown 格式的索引条目
- 将条目添加到索引文件的开头（按时间倒序）

**INDEX.md 格式**：
```markdown
| 入库时间 | arXiv ID | 论文简称 | 标题 | 路径 |
|---------|----------|---------|------|------|
| 2026-04-29 17:03:42 | 2405.03520 | Sora WM Survey | Is Sora a World Simulator? A Comprehensive Survey... | survey_reading/2405.03520-is-sora-world-simulator |
| 2026-04-28 09:15:00 | 2401.12345 | VideoGen Survey | A Survey on Video Generation... | survey_reading/2401.12345-video-generation-survey |
```

**命令**：
```bash
python scripts/step5_2_add_to_index.py 2405.03520 \
    --survey-dir survey_reading/2405.03520-is-sora-world-simulator \
    --cite-short "Sora WM Survey"
```

**参数说明**：
- `arxiv_id`：本篇综述的 arXiv ID
- `--survey-dir`：**必填**。具体的综述目录路径
- `--cite-short`：**必填**。本篇综述在索引中的简称

**输出**：
- 更新 `paper_database/Introduction/INDEX.md`
- 输出添加的索引条目信息

**前提条件**：
- 必须已完成 Step 4 的 Overlay PDF 构建
- 必须提供本篇综述的简称（`--cite-short` 参数）

**关键点**：
- 参考文献缓存使用 arXiv ID 作为主键，确保跨文章一致
- arXiv ID 已在步骤2生成 `citation_semantic_abbrevs.json` 时提取
- 索引按时间倒序排列，最新入库的论文在最前面
- 使用中国时间格式记录入库时间，必须精确到秒，格式为 `YYYY-MM-DD HH:MM:SS`
- 对于已先执行 Step 5.1 的论文，优先复用 `cite_short_cache.json` 中该 `source_survey` 的最早 `added_time` 作为 `INDEX.md` 的入库时间

---

## 时间统计要求（强制）

**每个步骤脚本必须自动输出详细耗时统计**，Agent 无需手动计时，直接使用脚本的输出即可。

**各步骤脚本必须输出的统计内容**：

**Step 1 必须输出**：
- PDF 下载：时间、文件大小、下载速度
- LaTeX 源码：下载时间、解压时间、文件大小、下载速度
- 总耗时

**Step 2 必须输出**：
- 解析 .bib 时间
- 写入模板时间
- 总耗时
- 待填数量

**Step 4 必须输出**：
- 复制源码耗时
- 各编译阶段耗时（pdflatex、bibtex、补丁写入、最终编译）
- 总耗时
- 输出 PDF 大小

**Step 5 必须输出**：
- 缓存更新耗时
- 索引更新耗时
- 总耗时

**输出格式**：每个脚本使用 `=` 分隔线，包含 emoji 图标，清晰可读。

**示例输出**：
```
============================================================
🚀 STEP 1: Materialize 完成 - 2405.03520
============================================================
📄 PDF 下载: 1.58 MB, 5.23秒, 309.45 KB/s
📦 LaTeX 源码: 12.45 MB, 10.90秒, 1.46 MB/s
⏱️  总计: 19.70 秒
============================================================
```

---

**网络代理**：
- 在中国大陆，优先尝试本地代理（如 `HTTP_PROXY=http://127.0.0.1:7890`）。
- 如果代理不可用，脚本应自动回退为直连或备用 URL，不要因为固定代理失效而直接中断流程。
