# 90 秒作品集演示分镜

本文档用于录制 AI-bioworkflow 的 GitHub、简历或作品集演示。目标是在 90 秒内证明三件事：结构化生信需求可以稳定编译，编译过程可审计，工具和容器受 Catalog 边界约束。

## 录制准备

- 使用 `1440x900` 或 `1920x1080` 视口，浏览器缩放保持 `100%`。
- 打开在线首页、`/workspace?example=rnaseq-deg`、`/runs` 和 `/catalog`。
- 选择“结构化示例”，保持 WDL syntax check 开启；该路径不需要 `DEEPSEEK_API_KEY`。
- 清理浏览器通知、书签栏和本地开发工具覆盖层，不展示 API key、主机路径或 raw model output。
- 优先现场创建一次成功 run；网络不稳定时，准备一个已成功 run 的详情页作为回退。

## 时间线与旁白

| 时间 | 画面与操作 | 建议旁白 |
| --- | --- | --- |
| 0-10 秒 | 首页项目名、一句话定位和主入口。 | “AI-bioworkflow 把自然语言或结构化生信需求转换成 Workflow IR，再确定性编译为经过校验的 WDL 1.0。” |
| 10-25 秒 | 进入 RNA-seq 工作台，展示 fastp、Salmon、tximport、DESeq2、MultiQC，点击“运行”。 | “稳定演示路径使用结构化 Recipe Tool Plan，不依赖模型 API key；recipe 和工具只能来自正式 Catalog。” |
| 25-42 秒 | 展示 run 状态、SSE timeline、WDL valid、行数和 diagnostics 摘要。 | “同一次 run 会持久化节点事件、Plan、IR、WDL 和诊断；WOMtool 校验通过后才标记成功。” |
| 42-62 秒 | 打开 Run 详情，聚焦 Workflow DAG，点选 `qc` 节点并展示 inputs、outputs 和 runtime docker。 | “DAG 来自 canonical Workflow IR，用于审阅 scatter、依赖关系和容器声明；它表达编译结构，不冒充真实任务执行状态。” |
| 62-75 秒 | 切换到 Catalog 页面，扫过 recipe steps、catalog-approved 与 e2e-validated 状态。 | “Catalog 同时约束 schema、命令模板和 runtime image，并把工具准入与执行验证分开记录。” |
| 75-86 秒 | 打开 Run 历史，展示成功与失败记录可回放。 | “历史页可以回放成功或失败 run；有界 Reviewer 只在确定性修复无安全动作时提出 IR patch，且必须重新通过完整编译链。” |
| 86-90 秒 | 回到首页或停在 DAG 全景。 | “这是一个强调编译器边界、生信建模与可观测性的工程作品集。” |

## 发布检查

- 成片控制在 `85-95` 秒，导出为 H.264 MP4，建议 `1080p`、`30 fps`。
- 字幕中的产品名、URL、WDL、Workflow IR 和 Catalog 大小写保持一致。
- 确认画面没有凭证、个人通知、内部 IP、临时 run payload 或浏览器账户信息。
- 上传后将视频 URL 替换到 README 首屏；在此之前保留“90 秒演示分镜”链接，不放无效占位地址。
