# daily-ai-infra — 拓源注册表（agent 的长期记忆，自生长）

> **和 `repos.json` 的分工**：
> - `repos.json` = **机器可读**，喂 `agent.py fetch`，决定每天抓哪些仓的 PR/Release。
> - `sources.md`（本文件）= **人类可读**，记「方向」和「术语」。`discover.py` 读这里的
>   「已知术语」判断什么算新；Claude 每天把新发现 append 到「候选观察」。
>
> 候选观察里的仓**连续几天出料** → 提升：加进 `repos.json` 的 `tracked`，并把本文件对应行
> 移到「已提升 / 已淘汰」留痕。长期无料 → 直接删。
>
> **只存源与术语，不存任何凭据。**

## 核心盘（稳定监控，真值在 `repos.json` 的 `tracked`）

本节只是给人看的摘要，**改动请改 `repos.json`**，不要只改这里。

### GitHub（PR + Release）
推理引擎：`sgl-project/sglang` · `vllm-project/vllm` · `NVIDIA/TensorRT-LLM` ·
`InternLM/lmdeploy` · `ai-dynamo/dynamo` · `llm-d/llm-d` ·
`huggingface/text-generation-inference` · `ggml-org/llama.cpp` · `deepseek-ai/DeepInfer`
Omni / 多模态：`vllm-project/vllm-omni` · `sgl-project/sglang-omni`
Kernel / 编译：`flashinfer-ai/flashinfer` · `tile-ai/tilelang` · `tile-ai/TileRT` ·
`deepseek-ai/DeepGEMM` · `deepseek-ai/TileKernels`
KV / 通信 / 并行：`kvcache-ai/Mooncake` · `deepseek-ai/DeepEP` · `deepseek-ai/DualPipe` ·
`deepseek-ai/3FS` · `deepseek-ai/DeepEP-Ascend` · `deepseek-ai/DeepGEMM-Ascend`
投机解码 / MLA：`deepseek-ai/DeepSpec` · `deepseek-ai/FlashMLA` · `lightseekorg/tokenspeed`
生态：`huggingface/transformers`
端侧单模型引擎：`Niko1221/Strata`（releases-only）

### 其他源（见 `agent.py fetch`）
arXiv（cs.LG/DC/AR/PF/CL/OS，推理关键词预筛）· HuggingFace Daily Papers · HF 模型发布
（deepseek 等组织）· Hacker News（Algolia）· Reddit r/LocalLLaMA · 11 个博客 RSS ·
LMSYS/SGLang blog（无 RSS，解析其 Next.js 内嵌 JSON —— 见 `pipeline/fetch.py:fetch_lmsys`）

### 自动发现机制（`agent.py fetch` 里的 `discovery` 配置）
- `orgs`: `deepseek-ai` — 该组织新出的 infra 仓（star ≥100、近 180 天有 push）自动进 tracked
- `awesome_lists`: `xlite-dev/Awesome-LLM-Inference` — 策展白名单，命中的仓晋升更快
- 提及计数：一轮内被提 ≥4 次 或 连续 3 轮出现 → 自动晋升 tracked

## 候选观察（拓源发现的暂存区，待提升或淘汰）

> 格式：`- <源> — <发现日期> — <一句为什么值得跟>`

<!-- 以下为从 personal_skills/ai-infra-daily-brief 迁移的既有发现，2026-08-07 导入 -->
- LMCache / Tensormesh — 2026-07-13 — KV cache 层独立商业化，$20M 融资 + AMD/NVIDIA/CoreWeave 战投
- TraCT（arXiv:2512.18194）— 2026-07-14 — CXL 共享内存做 rack-scale 分离式推理 KV 传输底座，替代 RDMA，claims 2.6x TTFT 降低
- ds4（`antirez/ds4`）— 2026-08-08 — antirez 写的 DeepSeek 4 Flash/PRO 本地推理引擎，一套代码覆盖 Metal/CUDA/ROCm，单模型专用引擎路线
- kimi-k3-in-c（`FareedKhan-dev/kimi-k3-in-c`）— 2026-08-08 — 2.78T Kimi K3 用纯 C99 在单 CPU + 8.24GB RAM 上跑推理，无 BLAS/框架/GPU，极限权重流式加载的教学级参考
- chitu（`thu-pacman/chitu`）— 2026-08-08 — 国产推理引擎，主打国产/异构加速卡适配，先挂观察看是否持续出料（同批挂入的 xllm / rtp-llm 已于 2026-10-21 淘汰）
- AFD（Attention-FFN Disaggregation）— 2026-08-08 — 把 decode 阶段的 attention 与 FFN 拆到不同 GPU 池，PD 分离之后的下一级拆分粒度（arXiv:2605.28302、2601.21351）；NVIDIA 收 Groq IP 的技术动机
- SpecForge（`sgl-project/SpecForge`）— 2026-08-08 — SGLang 的投机解码**训练**栈，v0.3.0 把 target/draft 训练解耦成分离式 + 共置两种模式，并放出 SpecBundle 开源 draft 模型系列；投机解码从「推理技巧」变成「要配套训练基建」的信号
- vllm-ascend（`vllm-project/vllm-ascend`）— 2026-08-08 — vLLM 官方社区维护的昇腾硬件插件，国产卡适配的主入口之一，先挂观察
- Miles（SGLang 生态的 RL / 训练框架）— 2026-08-08 — 与 SGLang rollout 深度绑定，Day-0 模型支持、MXFP8/NVFP4 RL 都从这里出；不是推理引擎但强影响推理侧精度格式，挂观察

- colibri（`JustVugg/colibri`）— 2026-09-22 — 纯 C 的前沿 MoE（744B–2.8T）消费级硬件引擎：VRAM/RAM/NVMe 三级统一层级、路由感知 expert 预取 + 学习式 expert 缓存，37k stars（Trending）；和 kimi-k3-in-c / ds4 同一谱系但更工程化
- turbo-fieldfare（`drumih/turbo-fieldfare`）— 2026-09-22 — Swift+Metal 把 Gemma 4 26B-A4B 跑进 ~2GB RAM：常驻 1.35GB 共享核 + KV，expert 从 SSD 按 LFU 流式加载，M5 上 31–35 tok/s，6.8k stars
- InferenceX（`SemiAnalysisAI/InferenceX`）— 2026-09-22 — SemiAnalysis 的持续推理基准平台：DeepSeek V4 / Kimi K3 / MiniMax M3 × GB200 NVL72 / B200 / MI355X × vLLM / SGLang，每日自动跑；2025-10 起，之前漏掉了
- AISimulate（`ai-dynamo/aisimulate`）— 2026-09-22 — Dynamo 1.5 把 AIConfigurator 改名独立成包，PD/并行配置的性能模拟器；配合 InferenceX 看「先仿真再部署」是否成常规

- InstinctFlash（`General-Instinct/InstinctFlash`）— 2026-09-24 — 面向机器人 VLA / world-action 模型的 serving runtime（AGPL），同一 API 覆盖 Jetson Thor + RTX，runtime 优化 1.2–7.9x、配合少步蒸馏调度器 LingBot-VA 达 33.78x；「边缘具身模型 serving」开始独立成栈（HN Show）。注意 FlashRT 提了署名争议 issue
- HySparse2 / MiMo-V3（arXiv:2609.26368）— 2026-09-24 — 小米下一代架构：外层 YOCO 式 KV Bridging（self-decoder 混合 SWA + cross-decoder 混合稀疏）+ 内层 token 级 KV Reuse，1M prefill FLOPs 约降 5x、KV 降 78%；模型发布后推理引擎要适配两级 KV 共享
- ModelExpress（`ai-dynamo/modelexpress`）— 2026-09-24 — NVIDIA 的权重/JIT 缓存分发层：优先从在跑副本 NIXL P2P RDMA 拉权重（DSV4-Pro 11s，比冷拉 HF 快 48x），今天同时在 vLLM（原生后端 #58399）/ Dynamo / llm-d 出现；冷启动与 RL refit 的共用底座

- Quail（`fsdatalab/quail`，Modal × CMU Full Stack Data Lab）— 2026-09-27 — AI-SQL 专用推理引擎：把 LLM 算子嵌进 SQL 查询计划，用 KV-aware join-order 搜索最大化前缀复用，Qwen3-4B FP8 单卡 H100 >10 亿 TPM、比 vLLM 快 1.84x；「查询优化器 × 推理引擎」联合优化的首个开源实现
- llama.cpp prompt-lookup n-gram cache 优化（jadidbourbaki.github.io 博客）— 2026-09-27 — 4 处 n-gram cache 改动让 prompt lookup 起草快 41.6x、静态 cache 加载快 23.5x；无模型投机解码在代码编辑类负载上的工程化，看是否合入上游

- NaiveAI / Naive-N0.5-Flash（`huggingface.co/NaiveAI`）— 2026-09-28 — 309B-A15.5B MoE、**全栈无 full attention**（SWA:DSA≈5:1 + GQA4）原生 1M 上下文，MIT；官方推理栈 megakernel + PDL + 投机解码（附 FP8 draft 权重）宣称 Ultrafast 2000 tok/s，且号称「AI 参与研发」；看 vLLM/SGLang 是否跟进纯 SWA+DSA 混合架构

> 排除记录：`dphnAI/sonar` = Aphrodite Engine 改名，**不是新项目**，别再当新发现（2026-08-08 查证）。

- MoonEP（`MoonshotAI/MoonEP`）/ UltraEP（`Dots-Infra/UltraEP`，arXiv:2606.04101）— 2026-09-29 — 实时动态冗余专家的 EP 库：每步按 token 负载复制热点专家并改路由，每 rank 计算量恒定、无 host 同步；DeepEP V2.5 的 `lb_prefetch_weights` 明确为它们提供原语，vLLM 也在提可插拔 EPLB policy（#59168），EP 负载均衡从「周期性重排」走向「逐步实时复制」
- System One 决策模型（Jev / `razorback16/openjev` / DiffusionGemma structured-read，vLLM PR #57250）— 2026-09-29 — 只输出带概率的结构化决策（choice/score/yes-no）而非文本；社区用 block-diffusion 模型单步去噪读槽位 logprob 复刻，Red Hat 已发 vLLM 部署文；新的推理工作负载形态（单步、无自回归 decode），观察是否会催生专门的 serving 路径。**2026-10-10 进展**：vLLM 主线 #59299 `/v1/systemone` 已合入（10-08，`--enable-structured-decisions`），llama.cpp/LiteLLM/Dynamo 同步铺接口，H2O-Lightning-4B 登 JevBench 第一——已从「社区复刻」进入「主流引擎一等端点」
- OpenEngine gRPC（`NVIDIA/TensorRT-LLM` #17992/#19371，Dynamo #14349/#15087）— 2026-09-29 — TRT-LLM 的 `openengine.v1` gRPC 协议（流式 Generate + Control RPC + KvSessionRef 分离式交接），Dynamo sidecar 与 KV-aware 路由改为走这个协议；看它是否成为引擎与编排层之间的通用接口

- Magnitude（`magnitudedev/magnitude`，YC S25）— 2026-10-01 — 面向本地 agent 的推理引擎，不发预编译 kernel 而是**在用户设备上现场编译+调优 kernel**，宣称 Metal decode 比 llama.cpp 快 92%、CUDA 快 19%，并按 agent 生命周期回收显存；Launch HN 157⬆/80💬、5.9k stars，「端侧 autotune 引擎」路线
- Galahad（`corbenicai/galahad`，arXiv:2609.39358）— 2026-10-01 — 跨请求**字节精确**的 KV 持久化（Taliesin：按文本块存盘/恢复 KV，262k logits 全一致）+ 文档按需切片（Blaise）；称真实数据集 98.7% prompt token 是「读过的」，兼容 vLLM/SGLang/llama.cpp；看能否成为 LMCache 之外的又一 KV 持久层
- ThunderEP（arXiv:2609.40093）— 2026-10-01 — PCIe 消费级卡（4090/5090）上的 EP 通信库：去掉 ring 冗余中继、走 DMA copy engine 不抢 SM、降低 host 内存 flag 轮询，dispatch/combine 比 NCCL 快 2.0x/1.53x，接入 vLLM 端到端 1.66x；DeepEP 不覆盖的「无 P2P」场景
- KVTether（arXiv:2609.39819）— 2026-10-01 — 追踪 agent harness 的语义原语（上下文改写/工具/子 agent）推断 KV 生命周期，及时回收死 KV、保住闲置待复用 KV，比 LMCache/MORI 延迟降 26.3%/17.4%；归入 agentic workflow-aware serving 子领域

- Spotlight（Percepta）— 2026-10-03 — 新架构：替换 attention 为「每 token 只读写恒定个数记忆单元」的无限外部记忆，知识/技能增长不改权重、算力不随记忆规模涨；若落地，serving 侧会多出一类「大容量可写记忆」的存储与检索负载，先观察是否开源/有论文

- MetaInfer（`HuangPuStar/MetaInfer`，Baseten 博客 2026-10-02）— 2026-10-07 — 用 coding agent（Claude/Codex/Pi）+ skills 为「指定模型×硬件×并行×量化」从零生成专用推理引擎；Baseten 的 VibeQwen 在 B200 上 Qwen3.6-35B 单流 decode 1792 vs vLLM 943 tok/s、TTFT 12 vs 28ms；「agent 生成单模型引擎」路线（与 Strata/ds4 手写单模型引擎对照），看是否有第三方复现
- Lachesis / HBF（arXiv:2610.08378）— 2026-10-07 — 按 KV 生命周期在 HBM 与 High-Bandwidth Flash 间放置 agent KV：短命 KV 留 HBM 吸收写入、长命 KV 下沉 HBF 以保护写寿命；HBF 作为 HBM 之下的新显存层级首次进入 serving 论文，观察 HBF 硬件进度与后续工作

- LiquidAI d1（`LiquidAI/d1-3B`、`LiquidAI/d1-omni-600M`，liquid.ai/blog/d1-open）— 2026-10-08 — 首个面向边缘的开源多模态**决策模型**：单次前向输出 yes/no、标签或 rubric 分数，0 输出 token，4090 上 8ms、Jetson Thor 16ms；llama.cpp 当天合入（b11483/b11488），Dynamo 同期在铺 decisions/systemone 端点，System One 决策模型从闭源走向开权重 + 端侧，归入该子方向持续跟
- ROCm 10.1 hipFILE / AMD Infinity Storage（rocm.blogs.amd.com）— 2026-10-08 — hipFILE 读写直接挂在 HIP stream 上、跳过 host 内存中转，加 NUMA 感知分配；AMD 对标 GPUDirect Storage，KV offload / 权重冷启动在 MI 系列上的存储直通底座，看 vLLM/SGLang 的 KV offload 是否接入

- SparseEngine（arXiv:2609.39068，HF Daily）— 2026-10-09 — 从零写的「稀疏优先」推理引擎：用统一生命周期契约让 15 种稀疏注意力/KV 驱逐方法各自控制 KV 表示，同时共用调度/前缀缓存；Chain Cache 让驱逐类方法跨请求续用历史、Prefix-Cache Pruning 剪中间历史仍保持前缀匹配；稀疏注意力从「单方法 patch」走向「引擎一等公民」，看是否开源/被 vLLM/SGLang 吸收
- TokenRouter（arXiv:2610.12242）— 2026-10-09 — token 级多模型路由的 serving 系统，解决多模型逐 token 交替时的 step 失步与 batch 准入延迟；路由粒度从 query/session 下沉到 token，观察是否形成新的 serving 形态
- Dynamo KvHint / Session-Prefix Indexer（PyTorch blog 2026-10-08；vLLM issue #51428、SGLang issue #27574）— 2026-10-09 — router 按 session 计算 KV 策略、以 Share/Prefetch/Demote/Pin/Retain 软提示下发给引擎执行（「programmatic KV cache」），SGLang HiCache 上 Share 已有实现；router↔engine 的 KV 策略接口，看两家引擎是否合入

- GPU 内 Locality Domains（CUDA 13.4 / Rubin sm_107；NVSHMEM 文档、PyTorch #198279、TRT-LLM #19541）— 2026-10-10 — Rubin 单卡内部按 SM+HBM 分成非一致访存域（GPU 内 NUMA），CUDA 13.4 首次暴露编程接口（按域分配显存 + 同域 green context）；vLLM 据此把 MoE 权重按列切到各域实现 locality-aware MoE（MiniMax M3 小 token 1.2x），TRT-LLM/PyTorch/NVSHMEM 同期跟进——kernel 与并行切分要多考虑一层「片内拓扑」
- GSQ-RCO（`huggingface.co/ISTA-DASLab`，Qwen3.8-Flash-Next GGUF）— 2026-10-10 — GSQ 用 Gumbel-Softmax 联合学 grid 分配与 group scale、RCO 在黎曼流形上按总尺寸预算做逐张量 bit 分配，产物仍是标准 GGUF 标量格式；IQ3_S 号称追平原模型、35 万+下载，Strata/Basalt 都把它当默认低比特权重——「学出来的非均匀混合精度」进入社区量化主流，看是否出 vLLM/SGLang 可用格式
- ML Drift（`google-ai-edge/ml-drift`，Google Developers Blog 2026-10-08）— 2026-10-10 — LiteRT 底下的端侧 GPU 推理引擎独立开源（Apache-2.0），一套抽象覆盖 OpenGL ES/OpenCL/Metal/WebGPU，张量虚拟化解耦逻辑/物理布局 + agent 辅助写 shader，宣称比现有开源 GPU 引擎快一个量级、TFLite GPU delegate 冻结；端侧 GPU 推理的第二条开源主线（对照 llama.cpp Vulkan/Metal），社区已在比 prefill
- Basalt（`jesdga95/basalt`）— 2026-10-10 — Strata 的 Blackwell 专用 fork，只跑 Qwen3.8-Flash-Next：5090+5060 Ti 异构双卡 665 tok/s 结构化 / 354 prose（2.6x Strata）、8 路并发、为低比特量化微调 MTP 头、权重重打包为单文件 .basalt；同时被评论质疑「vibe 写的引擎靠激活/KV 量化换速度」——单模型引擎路线开始出现 fork 链与质量争议，Strata 线持续跟
- Velo（`ai-dynamo/velo`）— 2026-10-10 — NVIDIA 的 Rust 分布式消息库（active message / typed stream / UCX-RDMA 大负载，静态链接 ucx-rs 无运行时 .so 依赖），Dynamo #15231 拿它做 response plane，2048 mock worker 下 5011 req/s vs 原 TCP 1847（~2.7x）；Dynamo 控制面通信栈在重写，看是否成为默认传输

- open-jet megakernel（`L-Forster/open-jet` 的 `megakernel/`）— 2026-10-11 — 持久化协作 kernel 把**整轮投机解码**（目标模型验证 T=1+n_draft、设备端接受判定、MTP 追平、n_draft 步起草，约 340 个 phase 用 grid barrier 串起来）放进一次 launch，权重全程保持 k-quant 编码；Qwen3.8-27B Q4_K_M 在 3090 上 1.5–1.9x llama.cpp（代码 140 vs 73 tok/s），作者称由 Claude Opus 5.5 写成。megakernel 的粒度从「一个 decode step」扩到「一整轮投机」，同类见 ForgeMegakernel（arXiv:2609.12379）、`PixelML/club-170hx` #86
- backburner（`StayLameBro/backburner`）— 2026-10-11 — 用 USB-C 把 iPhone 接成 Mac 的推理协处理器：split prefill（Mac 跑 1–40 层、iPhone 跑 41–64 层），64k 以后的最老 KV 页放在 iPhone 上并由它算这部分 attention；M4 Pro 24GB 上 Qwen3.8-27B 上下文 64k → 196–229k、prefill +29–44%，~940 stars，pre-release。「手机当 KV/attention 卸载节点」的端侧异构路线，看是否有人复现到其他设备组合
- dsv41-flash-offload（`sybil-solutions/dsv41-flash-offload`）/ Infernix（`wallawalla47/infernix`）— 2026-10-11 — 单模型引擎扩到 DeepSeek-V4.1-Flash：单张 3090 + 256GB DDR4，15,360 个路由专家分在 VRAM 缓存 / pinned DDR4 / CPU 计算三层，Engram n-gram 表 mmap 在 NVMe，staged-DMA prefill；decode 19–27 tok/s（1–4 流）、prefill 690–790 tok/s 到 261k。Infernix（NInfer 衍生）同样把 52GB n-gram 嵌入表放 NVMe——「Engram/n-gram 表下沉 NVMe」正在成为这类引擎的固定设计，和 oMLX 的 SSD N-gram Offload 同一思路
- kyojin（`Yamz-Labs/kyojin`）— 2026-10-11 — 基于 ExLlamaV3 的 AMD Strix Halo（gfx1151）专用引擎，128GB 迷你主机跑 Qwen3.8-Flash-Next / GLM-5.3-Flash / MiMo-V2.6-Flash，投机解码下 26–67 tok/s；99 stars，信号弱，先记着。**2026-10-12 进展**：trendshift llm-inference 榜显示已约 1 万 stars（未经 GitHub API 核实），信号转强，继续跟

- Project Maya（`mw00/project-maya`，Strata PR #1420）— 2026-10-12 — Strata 为 GLM-5.3-Flash（321B MoE）重写的引擎：专家按热度分 VRAM / RAM / NVMe 三层，自带 MTP、双卡层切分、OpenAI/Anthropic 兼容 API 和量化工具；Maya-S 是 96.5GB GGUF，据报道在 2×V100 32GB + 30GB RAM 上 decode 40 tok/s、prompt 440 tok/s，MIT。Strata 线从「单模型」扩成「按模型重写的引擎家族」，Strata 已通过 #1420 反向合入 GLM 支持

- FastEEP（arXiv:2610.18451）— 2026-10-14 — MoE serving 的「实例内弹性 EP」：负载波动时直接在运行中的实例里扩缩 EP 组，而不是销毁重建整个实例；和 TRT-LLM DynamicEPLB（#19646）、MoonEP/UltraEP 同属「EP 从静态配置变成运行时可调」这一线，看是否有引擎实现
- ATOM（`ROCm/ATOM`，AMD 基于 AITER 的轻量推理引擎）— 2026-10-14 — llm-d #2351 已合入 ROCm ATOM 支持、#2386 在接 ATOM + MoRI-IO 的 P/D；AMD 侧除 vLLM/SGLang ROCm 之外的第三个引擎入口进入主流编排层，另有 ATOMesh（多节点）、SGLang-ATOM、vLLM RFC #33478 把 ATOM 作模型实现后端，先挂观察
- llm-d FMA + KEDA scale-from-zero（llm-d #2799/#2752/#2794）— 2026-10-14 — FMA（Fast Model Actuation，`guides/fast-model-actuation`，模型快速拉起/休眠）配 KEDA 按 EPP 队列触发从 0 扩容，nightly 已有矩阵测试；推理服务「缩到零」开始成为 well-lit path，和 TRT-LLM KV cache manager V2 的 tier 化 sleep/wakeup（#20087）一起看冷启动路线

- Radiance（`codeberg.org/StillDeadcode/radiance`，前身 `drwolfen/radiance-vllm-qwen4exp` / vllm-radiance）— 2026-10-15 — 只为 AMD RDNA4（gfx1200/gfx1201，Radeon AI PRO R9700）写的 C++/HIP 推理引擎：从 vLLM 补丁 fork 起家后完全重写，模型结构、kernel 库、量化器都做成运行时加载的 .so 插件，权重打成单文件 .rad（4-bit codebook 专家 + int8 主干 + MTP 头）；据 r/LocalLLaMA 帖子，2×R9700 + 64GB DDR5 上 Q4 Qwen3.8-Flash-Next decode 176 tok/s、prefill 6450 tok/s，Level1Techs 有多卡实测。消费级 AMD 卡也开始有专属引擎（对照 kyojin 之于 Strix Halo），托管在 Codeberg 而不是 GitHub，`agent.py` 抓不到，靠社区源跟。**2026-10-16 进展**：同作者的前身 affinity（`codeberg.org/StillDeadcode/affinity`，DeepSeek-V4-Flash 专用，已标 deprecated、部分并入 Radiance）被社区在 4×R9700 上实测：作者原本限 ≤2 卡，4 卡下 11,008 个专家全部常驻 VRAM、decode 79 tok/s（2 卡时 36 tok/s，82% 时间在等 host 专家流），稳定性补丁在 `neuromaniacMD/affinity` 的 v4-fixes 分支
- Telperion GQA→GLA/MLA 改装（`huggingface.co/TelperionAI`，Qwen3.8-27B-MLA / Qwen3.8-27B-GLA-g2）— 2026-10-15 — **不训练**，把现成 Qwen3.8-27B 的 16 层 full-attention 的 K/V 投影改成低秩 latent：MLA 版共用一个 latent，KV 缩到 1/4；GLA-g2 把 latent 分 2 组、每组服务 12 个 query head，所以能像原 KV head 一样按 TP=2 切开（TP2 下每卡每 token 从 32 KiB 降到 16 KiB）；SWE-bench Verified 0.394 对原模型 0.395，生成 token 少 14%，已出 FP8/INT4/EXL3。从 TransMLA 类工作延伸出来的「模型发布后由第三方改注意力结构换 KV 容量」路线，看 vLLM/SGLang 能否直接加载 GLA 结构

- Janas（`prabanta-dev/janas`）— 2026-10-16 — 纯 C、零依赖的 **CPU-only** MoE 引擎：用 RAM 做专家缓存、其余专家从 NVMe 流式读取，作者称 Core Ultra 9 185H 笔记本上 Qwen3-Next-80B 达 37 tok/s（llama.cpp 2.8）；r/LocalLLaMA 有人移植到 ARM（NEON/i8mm，逐 bit 对齐标量参考实现），在 £300、35W 的骁龙迷你主机上 80B 配 MTP 跑到 17–18 tok/s。专家流式这条线（colibri / turbo-fieldfare）延伸到没有 GPU 的机器上；GPL-3、419 stars、早期
- capy-flash（`ValerioDolci/capy-flash`，前身 ninfer-tp2）— 2026-10-16 — 双 RTX 5070 Ti 16GB 张量并行跑 Qwen3.8-Flash-Next 125B（NVIDIA 官方 NVFP4 原样加载），VRAM 里按 expert id 分卡缓存专家、未命中的专家在 CPU 上用 AVX-512 NVFP4 kernel 算，decode 100.8 vs Strata 78.3 tok/s；附带发现：TP=2 时各卡在 all-reduce 前把部分和舍入成 BF16，相当于舍入两次，Qwen3 上大误差出现频率约为单卡的 5 倍，部分和改用 FP16（字节数相同、精度高 8 倍）即可回到单卡水平——对所有 TP 引擎都适用的数值一致性细节；37 stars
- ALoDLM（`huggingface.co/amazon/ALoDLM-8B`，arXiv:2610.04198）— 2026-10-16 — Amazon 的「自适应循环」扩散 LM：从 Qwen3-8B 初始化，共享 transformer 层反复迭代，已确定的 token 提交、不确定的保留 latent 继续循环（学出来的 exit gate + 置信度阈值），社区称推理约 3x 于 Qwen3-8B；自带 nano-vLLM 引擎，CC BY-NC。循环（per-token 可变深度）+ 扩散并行解码叠在一起，serving 侧要处理逐 token 不同的计算量，看主流引擎是否跟进
- Prime Inference（primeintellect.ai/blog/prime-inference，2026-10-02）— 2026-10-16 — Prime Intellect 的多数据中心 serving 平台，栈是 vLLM + Dynamo（P/D 分离，p90 ITL 降约 40%）+ Mooncake（host DRAM 前缀缓存）+ FlashInfer，NVFP4 KV 容量 +50%；P/D 传输把 KV 布局从 layer-major（LBHNC）改成 block-major（BLHNC），传输描述符从约 19,559 降到 1,940，KV 传输 146→78ms，并回馈 upstream（FlashInfer 原生 NVFP4 kernel）。看 block-major 布局是否进 vLLM/NIXL 主线
- MLX 分布式推理（jaccl，Apple ML Research 2026-10-15）— 2026-10-16 — Apple 官方的 Mac Studio 集群推理：自研通信库 jaccl 走 Thunderbolt 5 上的 RDMA，每对机器双线直连，支持 PP 和 TP；4×M5 Ultra 用 TP 跑 Muse Spark Open（816B）超过 36 tok/s（64k 上下文）。消费级 RDMA 集群成了 Apple 官方路线，对照 backburner（iPhone 当协处理器）和 Radiance 多卡

- ORL / dlmrt（`yifan1130/orl-dlm`，arXiv:2610.20687，HF `yifanyu/*-ORL`）— 2026-10-17 — 扩散 LM 的「残差上下文」加速：把上一步去噪的预测分布带进下一步，用模型自己的残差轨迹做 on-policy 训练（熵收缩目标），QwenDLM-4B 上每次前向产出 token 数最高 6.2x；配套专用引擎 dlmrt，端到端约 6.9x，单张 RTX 5090 跑 LLaDA-2.1-mini 达 2,788 tok/s，H100 单请求比 DFlash 投机快 1.74x。dLLM 开始有自己的 serving 引擎，对照 ALoDLM 的 nano-vLLM，看 vLLM/SGLang 是否跟进
- deepseek-recipe（`deepseek-ai/deepseek-recipe`）— 2026-10-17 — 随 DeepSeek-V4.1-Flash-1017 发布的 Rust 协议层（带 Python 绑定）：把 Messages / Chat Completions / Responses 请求转成 DeepSeek V4/V4.1 的 prompt 或 token id，再把输出解析回流式响应（thinking / 工具调用 / 图像），推理与传输留给调用方；1017 起不再提供 Jinja chat template。模型厂商自带协议层（对照 Beam 的 Rust harness、tokenspeed 的 Symphony parser），看各引擎是否改为直接依赖它
- vLLM latency_specialized decode 后端 + fast-track 模型优化 RFC（vLLM 博客 2026-10-16，PR #61867 / #61868）— 2026-10-17 — agent 写的 CuTe DSL 单模型 decode 路径（K3 每层 23 个 kernel → 13 个、130→69µs），用 `decode_backend: latency_specialized` 开关隔离在模型代码内，靠标准化正确性/性能基准替代逐行人审；DSV4.1-Flash、GLM5.3 跟进。「agent 生成的 kernel 怎么合进主线」开始有流程，看 RFC 是否落地
- Strata 量化 / fork 链（`agentionai/Qwen3.8-Flash-Next-Gyro-GGUF` 及其 GYRO fork、`bodhi37/strata`）— 2026-10-17 — r/LocalLLaMA 上同日两条：GYRO 系列量化号称 KLD / top-1 都优于 ISTA 的 GSQ-RCO 且更小，并配套一个 Strata fork；bodhi37 的 Strata fork 在 12GB VRAM + 32GB RAM + NVMe 上跑 GSQ-RCO IQ3_S 的 Qwen3.8-Flash-Next，131k 上下文 decode 40–50、prefill 1300–1500 tok/s。都是单人项目、未经第三方复现，先记着看是否持续

- Xolotl（`Indras-Mirror/Xolotl`，原名 Strata-DSV4.1）— 2026-10-18 — Strata 的大幅扩展 fork（约 +7.1 万行），在 1×RTX 4090 + 90GB DDR4 + NVMe 上跑完整 552B 的 DeepSeek-V4.1-Flash：专家分 VRAM / pinned RAM / NVMe 三层按 token 拉取，decode ~27 tok/s、prefill 180–320 tok/s、512K 上下文；量化是「Engram 表不动（约 200GB）+ dense Q8 + 专家按敏感度混 1/2/3 bit」。同一引擎还跑 GLM-5.3-Flash / Qwen3.8-Flash-Next / 27B。对照 dsv41-flash-offload 要 256GB DDR4，这里把 RAM 需求压到 90GB；MIT、68 stars、单人项目，看 1017 版量化出来后是否有第三方复现
- 异构设备链 + 流水线投机（r/LocalLLaMA 1x8ley0）— 2026-10-18 — 2 台游戏 PC（2060S / 9060 XT）+ M4 Pro MacBook（以太网）+ 2 台 iPhone 17 Pro Max（USB-C）串成 5 段 PP 跑 Qwen3.8-Flash-Next：iPhone 只算部分层里被选中的专家（约 1ms 回包），PC1 上的 MTP 头在上一批还在链上走时就起草下一批，把 PP 气泡藏进投机里；每步约 2.2 token，60k 上下文 decode 37–39 tok/s。对照 backburner（iPhone 当 KV/attention 节点）和 MLX jaccl，消费级异构集群开始用「投机 + 流水」解 PP 空转；作者未给仓库链接，先记方法
- llama.cpp adaptive KV streaming ROCm 移植（上游 `RaymondHuang210129/llama.cpp-adaptive-kv-streaming`，436 stars）— 2026-10-18 — 完整 262k KV 留在 host RAM（~7.4GB），每步只经 PCIe SDMA 异步搬有界工作集（prefill ~450MiB / decode ~2.1GiB），prefill 用 online LSE 跨流式页累加、层 L+1 的传输与层 L 计算重叠；16GB RX 9070 XT 上 Qwen3.8-27B IQ4_XS 全 262k 上下文 decode 80+ t/s。KV 也开始像专家一样「不常驻显存、按工作集流式」，看是否进 llama.cpp 主线

- Kapitsa（`nace-ai/kapitsa`）— 2026-10-19 — Apple Silicon 上只服务 Qwen（GDN+attention）和 Nemotron-H（Mamba-2+LatentMoE）两族的 Metal 引擎：按架构 × 权重格式（MLX affine / NVFP4 / NVIDIA 2-bit 专家）手写 kernel，投机用 DFlash2 / DSpark / LiLiCorr，混合模型在轮次边界存 KV + 递归状态检查点，27B 和 Bolt 的部分 prefill 放到 Neural Engine 上；M4 Pro 上 Qwen3.8-27B 63 tok/s（MLX 28、llama.cpp 18，作者自测）。10-16 建仓、114 stars，「单模型族专用引擎」从 CUDA（Strata）扩到 Metal，看第三方复现
- SonicBoom（`hardenedlinux/SonicBoom`）— 2026-10-19 — HardenedLinux 社区的 compiler-first 推理运行时（GPLv3）：模型图经自有 Boom IR（MLIR 方言）→ linalg → gpu → nvvm 按形状 JIT，热点量化 matmul 沿用 ggml kernel，C ABI + Guile Scheme，无 Python；v0.0.3 在 RTX 3050 上 decode 为 llama.cpp 的 1.12–1.18x，前缀复用与完整 prefill 逐位一致，每项优化可单独开关并给消融数。只验证了 2 个小模型、只有 greedy、8 stars，先记着看是否长大
- eidola-engine（`eidola-ai/eidola`）— 2026-10-19 — 面向机密计算的自托管推理引擎，Rust 写的窄核心：连续批处理 / 分页 KV / 加盐 SHA-256 前缀缓存 / 投机解码，配一个逐位复现调度全过程的 CPU 参考执行器当 oracle，B200/B300 的 CUTLASS + DeepGEMM kernel 提前编译且构建字节可复现（PR #374，10-07 合入，首个模型 MiMo-V2.6）。「可审计、可证明」的推理栈，5 stars，看是否有 TEE 部署方采用
- PegaFlow（`novitalabs/pegaflow`）— 2026-10-19 — Rust 写的 KV cache 存储 sidecar：GPU→host RAM / SSD 卸载、RDMA 跨节点共享、按 PCIe 拓扑安排传输，vLLM 已接（2026-05 与 vLLM 联合博客），218 stars。和 LMCache / Mooncake Store 同一层，novelty 搜索撞见、今天无新料，先挂着看是否有 SGLang 接入或新版本

- dsx（`lxe/dsx`）— 2026-10-20 — 只服务 DeepSeek-V4.1-Flash-1017 的 Rust + CUDA 引擎，自带 2-bit 量化：2×RTX 3090 + 128GB RAM 上 decode 约 29 tok/s、prefill 300–470 tok/s，路由不剪专家；启动时测每张卡的 host 链路带宽，链路最好的卡放 dense 权重和 KV，其余卡装专家，快链路的卡随对话逐 token 换入热专家（`DSX_ADAPT`）。同 Xolotl / dsv41-flash-offload 一个谱系，RAM 需求介于两者之间（90GB / 256GB）；MIT、24 stars、10-18 建仓，r/LocalLLaMA 已有人基于它出 2.6 bpw 量化
- Maxwell（heymaxwell.ai）— 2026-10-20 — 自称「code execution model」：盯着运行中的程序，把 Python / PyTorch 热点重写成针对本机的机器码或专用 kernel，每次替换都附形式化等价证明（复用「proof gadget」），不改源码；宣称 AI 推理 kernel 4.25x、LTX-2.5 4K 视频生成 250s→134s、一天内在 90% 的 Blackwell kernel 上超过 NVIDIA PyTorch 基线。闭源早期访问，HN 55⬆/29💬。「带证明的运行时重写」和 agent 写 kernel 是两条路，先看有没有第三方复现
- berth（`T-Crypt/berth`）— 2026-10-20 — 本地多引擎的 GPU 租约仲裁器（Go 单二进制）：chat / 图像 / 语音引擎轮流租用同一张卡，不会两个同时加载互相 OOM，还能作为统一 API 端点按需拉起 Strata、llama-swap、ComfyUI 等；38 stars。消费级「一卡多引擎」开始需要调度层，信号弱，先记着
- NVIDIA CompileIQ + Helion ACF（PyTorch 博客 2026-10-19）— 2026-10-20 — 把 ptxas 的寄存器分配 / 指令调度等编译控制（CUDA 13.3 起开放，打包成 Advanced Control File）当成 autotune 的一个维度，和 Helion 的 tile / warp 配置联合搜索；已调好的 NVFP4 decode GEMV 再快 4.7–6.9%。「kernel 调优往下伸到汇编器」，看 vLLM / SGLang 的 Triton / CuTe kernel 是否开始随仓发 ACF
- Narwhal（`athrael-soju/Narwhal`）— 2026-10-21 — 「无固定角色」的分离式推理：按实测引擎画像 + 当前负载给 P/D 配比打分，一次只把一个引擎换角色、权重常驻不重载，NIXL 传 KV，带热备 router；单卡可起 2–8 个引擎做开发。Awesome-LLM-Inference 增量，8 stars 很早期；和 llm-d #2889 动态 P/D、vLLM Elastic EP 同一条「拓扑运行时可调」线，看是否有人接
- open_rknpu2_lm_infer（`happyme531/open_rknpu2_lm_infer`）— 2026-10-21 — 不用瑞芯微闭源 RKLLM 用户态库、直接驱动 RK3588 NPU 的 LLM 引擎（Rust 上层 + C++ NPU 算子），Qwen3.5-4B 带 MTP 时 prefill/decode 都约为 RKLLM 1.3.1 的 2.5×/1.9×，支持前缀缓存与工具调用，计划接 DFlash/DSpark；边缘 NPU 也开始出现「绕开厂商 SDK」的社区引擎
- Gufo（r/LocalLLaMA，MIT）— 2026-10-21 — AMD Strix Halo 专用引擎（约一个月前发布），首篇博客讲「大统一内存、低带宽」下怎样缓存混合（attention + 线性）模型的状态；与 kyojin / Halogen 同属 Strix Halo 单芯片引擎谱系，先记着看博客系列
- AKV / Cache Engineering for Agents（arXiv:2610.28577）— 2026-10-21 — 让 agent 直接对自己的活跃 KV 做 drop / repos（改位置编码）而不是改写上下文，避免摘要式压缩触发重 prefill；指出同一 token 序列在不同 cache 操作历史下 KV 不同、前缀匹配不再足以判定可复用，配套 AKV serving 引擎对外无状态、内部管理有状态复用。看引擎侧是否出现「cache 操作历史」作为前缀键的一部分

- KVCompass（arXiv:2610.24179，Shiyi Ling 等，2026-10-16）— 2026-10-22 — 「互联网规模」前缀缓存共享的**发现平面**：同一模型跨地域多集群部署时，各区重复 prefill 同一批热门前缀；KVCompass 用最小完美哈希（MPH）把全量 KV 索引压到能整份复制进每个边缘节点的 DRAM，变长前缀查找变成本地常数时间读，再按「复用收益 × 负载 × 网络距离」选 worker；P99 TTFT 比基线低 1.3–14x，吞吐最高 4.7x。前缀缓存从集群内（LMCache / Mooncake / llm-d prefix-aware router）往跨区域走，看有没有引擎 / 路由层接
- LES / llama.cpp-omni（OpenBMB，Lookahead Expert Scheduling，r/LocalLLaMA 1xbmsgf）— 2026-10-22 — 手机端跑 35B-A3B MoE（MiniCPM-V 4.7）不剪专家、不改路由：预测下一层会用的专家、在当前层算的时候从 flash 预取，先算已就位的专家；配权重布局 + 混精量化 + DSpark 投机，iPhone 18 Pro Max 上 20.51 tok/s（基线 3.38，6.07x），专家权重小 26.7%、五项基准掉 0.16 分，低内存配置峰值约 3 GB；实现开源在 llama.cpp-omni。评论指出 Strata 的跨层专家预载是同一思路；「专家流式」从 PC（Strata / Janas / turbo-fieldfare）下探到手机，看 llama.cpp 主线是否吸收
- VocabX 词表专精（HF 博客 `Dharma-AI/vocabx-vocabulary-specialization`）— 2026-10-22 — 把推理成本优化做到 tokenizer 层：子词层按领域重切、多词层用 5 种 miner 把反复出现的行 / 表达式 / JSON 结构合成「宏 token」，两层共用一个**以 decode 代价为权重**的成本准则（生成一个 token = 一次完整前向，比读入贵得多）；生产中的 Qwen3-4B 葡语作文评分器输出 token 350→101，RTX 5090 + vLLM 500 请求实测成本 -77%，分数还涨（0.703→0.810）；Qwen3 / Llama-3.1 / Gemma-3 × 5 领域都优于参考方法。思路是「少生成」而不是「生成得快」，和投机解码正交；看是否有引擎 / 平台把词表替换做成部署选项
- HAWK（arXiv:2610.29873）— 2026-10-22 — GPU 做 prefill、NPU 做 decode 的**跨厂商** P/D 分离：NPU 侧按 tensor 布局预排的 RDMA 缓冲区让 KV 直传直用、免重排；在同等 SLO 下达到纯 GPU 方案的 92%，能效 1.26x、成本效率 1.72x。同日 llm-d #2897 / SGLang #45377 把 Intel XPU 也接进 P/D，「P/D 两端用不同硬件」从论文走向部署脚本，看 NIXL / Mooncake 是否出现跨厂商 KV 传输适配层
- UlaCache（arXiv:2610.29820）— 2026-10-22 — 面向稀疏注意力 serving 的 KV 管理：跨 GPU 池 + 可选 CPU 内存的**统一逻辑地址空间**，引擎按稳定逻辑引用分配 / 选择 KV、与物理位置解耦，DP / TP attention 共用一套分配与稀疏访问接口，共享 GPU 池用并行分桶 LRU（PB-LRU）做元数据更新与淘汰；开投机时 H200 上 1.16x（DP）/ 1.70x（TP），B300 上 1.73x / 2.51x。和 vLLM AuxOutput「indexer 选择回放」（#62915）、AKV 一样在解「稀疏选中的 KV 怎么长期可寻址」，看是否有引擎采用逻辑地址这一层

## 已提升 / 已淘汰（留痕）

> 提升：`- <源> — promoted <日期> — 已加入 repos.json tracked`
> 淘汰：`- <源> — dropped <日期> — <为什么不跟了>`

- LMDeploy（`InternLM/lmdeploy`）— promoted 2026-08-07 — 已在 repos.json tracked 中
- DeepJIT（`deepseek-ai/DeepJIT`）— promoted 2026-09-22 — org-watch 自动进 repos.json tracked；header-only C++20 JIT 运行时，CUDA + 昇腾 NPU 双后端，DeepGEMM 全部 kernel 经它运行时编译
- DeepSelect（`deepseek-ai/DeepSelect`）— promoted 2026-09-22 — org-watch 自动进 repos.json tracked；DSA（V3.2/V4/V4.1）TopK + 采样器 kernel，比 torch.topk 快 2–20x
- DeepGEMM-Ascend / DeepEP-Ascend（`deepseek-ai/DeepGEMM-Ascend`、`deepseek-ai/DeepEP-Ascend`）— promoted 2026-10-01 — org-watch 自动进 repos.json tracked；DeepSeek 算子栈的昇腾 950 分支，与 FlashMLA/DeepSelect 950 版同日落地
- Strata（`Niko1221/Strata`）— promoted 2026-10-11 — 已加入 repos.json tracked（releases-only，PR 不抓）；2026-10-03 起 r/LocalLLaMA 连续出现，10-10 有 Basalt fork、10-11 有 strata-mlx（MLX 移植）、Strata-DualGPU 和 RTX PRO 6000 实测，21k stars，3 天发了 5 个 release（v0.1.40.2→v0.1.42）
- Eval-infra（Braintrust / Judgment Labs / Bigspin.ai）— dropped 2026-10-15 — 2026-07-12 挂入后 90 天无料，且属推理下游的 eval 层，不在本 agent 的推理栈范围
- OmniRoute（`diegosouzapw/OmniRoute`）— dropped 2026-10-15 — 2026-07-13 挂入后无料，应用层 AI 网关，不是推理基建
- ParoQuant（`z-lab/paroquant`）— dropped 2026-10-15 — 2026-07-14 挂入后 90 天无后续（无引擎接入、无新版本），单篇量化方法
- TurboQuant+（llama.cpp Discussion）— dropped 2026-10-15 — 2026-07-14 挂入后无合入上游迹象，90 天无料
- BanaServe（SP&E 2026）— dropped 2026-10-15 — 期刊单篇，2026-07-14 挂入后无开源/后续
- parallax（`GradientHQ/parallax`）— dropped 2026-10-15 — 仓库最后 push 停在 2026-07-01（discover rising 实测），2026-08-08 挂入后无料
- DeepSeek-Reasonix（`esengine/DeepSeek-Reasonix`）— dropped 2026-10-15 — 应用层 coding agent，2026-08-08 挂入后未再出现「按缓存特性反向设计」的同类信号
- Aphrodite Engine（`aphrodite-engine/aphrodite-engine`，现名 `dphnAI/sonar`）— dropped 2026-10-16 — 2026-07-12 挂入，96 天内日报从未出料；discover rising 显示 sonar 最后 push 在 2026-09-11
- Modular MAX / BentoML — dropped 2026-10-16 — 2026-07-12 挂入，96 天无实质料（BentoML 只以成名老仓身份出现在 rising），不再算「起势」
- Bessemer「AI Infrastructure Roadmap」— dropped 2026-10-16 — 2026-07-12 挂入后无新版，VC 季度报告不是持续出料源
- kvcached（`ovg-project/kvcached`）— dropped 2026-10-18 — 2026-07-13 挂入，日报（2026-09-22 起 18 期）从未出料，只以老仓身份反复出现在 discover rising
- HF Kernels Hub（huggingface_hub）— dropped 2026-10-18 — 2026-07-14 挂入，18 期日报无料，kernel 分发没有出现新的引擎接入信号
- MTPLX（`youssofal/MTPLX`）— dropped 2026-10-18 — 2026-08-08 挂入，18 期日报无料，只出现在 rising；Apple Silicon MTP 投机这条线已由 Strata/MLX 系覆盖
- kvpress（`NVIDIA/kvpress`）— dropped 2026-10-18 — 2026-08-08 挂入，18 期日报无料，KV 压缩方法库只在 rising 出现
- HPC-Ops（`Tencent/hpc-ops`）— dropped 2026-10-18 — 2026-08-08 挂入，18 期日报无料
- Agentic workflow-aware serving 子领域（Helium/Nalar/Cortex/HexAGenT/Pythia）— dropped 2026-10-19 — 2026-07-13 挂入，20 期日报（2026-09-22 起）一次都没出料；agent 负载相关的信号实际来自引擎侧（session 前缀索引、会话续接、DLite 这类 agent 投机），已被核心盘覆盖
- llm-d-kv-cache（`llm-d/llm-d-kv-cache`）— dropped 2026-10-20 — llm-d v1.0.0 release notes 写明已并入 `llm-d-router`（旧库只为迁移暂留），不再是独立的源，由 tracked 里的 `llm-d/llm-d` 覆盖
- DeepInfer（`deepseek-ai/DeepInfer`）— promoted 2026-10-21 — org-watch 自动进 repos.json tracked；DeepSeek 生产推理框架开源版（最初基于 vLLM，目前只支持 DeepSeek-V4.1-Flash、SM100 / 昇腾 950，离线推理，不含 KV cache 系统、PD 分离胶水和 DP 负载均衡），10-16 建仓、10-20 公开，10-21 已 15.7k stars，两天内 92 个 PR 几乎全来自社区移植（SM90 / 昇腾 910 / MPS / Biren / XPU / Vulkan），维护者已明确拒收 SM90 移植
- xllm（`xLLM-AI/xllm`）/ rtp-llm（`alibaba/rtp-llm`）— dropped 2026-10-21 — 2026-08-08 挂入（74 天），2026-09-22 起的日报一次都没出料，xllm 只以老仓身份出现在 discover rising；国产卡适配的信号实际来自 DeepInfer / DeepSeek 算子仓的昇腾、壁仞、MUSA 移植
- VibeServe（`uw-syfi/vibe-serve`，arXiv:2605.06068） — dropped 2026-10-22 — 2026-09-22 挂入满 30 天，2026-09-23 起的日报一次都没出料
- BaseRT（arXiv:2607.00501 / 2607.19438） — dropped 2026-10-22 — 2026-09-22 挂入满 30 天，2026-09-23 起的日报一次都没出料
- ANEForge（`sbryngelson/ANEForge`） — dropped 2026-10-22 — 2026-09-22 挂入满 30 天，2026-09-23 起的日报一次都没出料
- Gewell / Splash Engine — dropped 2026-10-22 — 2026-09-22 挂入满 30 天，2026-09-23 起的日报一次都没出料
- unalloc（arXiv:2609.24991） — dropped 2026-10-22 — 2026-09-22 挂入满 30 天，2026-09-23 起的日报一次都没出料

## 已知术语（判断"什么算新"的基线）

> `discover.py` 解析本节，见到不在这里的词 = 新方向信号。Claude 每天把确认过的新术语
> append 到这里，避免明天又当"新"重复发现。逗号或换行分隔均可。

vLLM, SGLang, TensorRT-LLM, TGI, llama.cpp, LMDeploy, Dynamo, llm-d, Mooncake,
PagedAttention, RadixAttention, FlashAttention, FlashInfer, FlashMLA, Triton, CUTLASS,
TileLang, TileRT, DeepGEMM, DeepEP, DeepSpec, DualPipe, 3FS, TileKernels, tokenspeed,
FP8, NVFP4, INT4, INT8, MXFP4, AWQ, GPTQ, GGUF, SmoothQuant,
KV cache, prefix cache, chunked prefill, continuous batching, disaggregation, PD 分离, EPD,
MoE, expert parallel, tensor parallel, pipeline parallel, data parallel, sequence parallel,
speculative decoding, MTP, EAGLE, Medusa, lookahead decoding,
deterministic inference, batch-invariant, long context, RoPE, GQA, MQA, MLA,
Blackwell, Hopper, B200, GB200, GB300, H100, H200, MI300, NVLink, InfiniBand, RDMA,
CUDA, CUDA graph, torch.compile, CUTLASS, cuBLAS, ROCm, XPU, NPU, Ascend, KleidiAI,
TRTLLM, TRT, OpenVINO, ONNX, ONNX Runtime, TensorRT, OpenAI Triton, Ray, Ray Serve,
DeepSpeed, FasterTransformer, LightLLM, Xinference, LocalAI, KTransformers, PowerInfer,
Aphrodite, Modular MAX, BentoML, MLX, Ollama, LocalAI,
kvcached, LMCache, Tensormesh, OmniRoute, ParoQuant, TurboQuant+, BanaServe, TraCT,
HF Kernels Hub, CXL KV transfer, workflow-aware serving, prefill deflection,
Braintrust, Judgment Labs, Bigspin, DSpark,
GEMM, LoRA, Multi-LoRA, TTS, VLA, GLM, MiniMax, Qwen, Llama, Mistral, Kimi, DeepSeek,
BugFix, KEDA, kserve, GPUStack, PowerInfer, LMCache, BentoML, lorax,
<!-- 2026-08-08 新增（查证过的，含判定"不值得跟"的，避免明天重复发现） -->
KDA, Kimi Delta Attention, LatentMoE, MoonViT3d, HiCache, FlatKV, DCP,
decode context parallelism, DSA, DeepSeek Sparse Attention, AFD, Attention-FFN Disaggregation,
NIXL, EFA, libfabric, AITER, MORI, Gluon, CuTe, CuTe DSL, quack-kernels, megakernel,
AlphaMoE, MegaMoE, mega-MoE, W4A4, W4A16, W8A8, MXFP8, SwiGLU, ServerArgs, EngineCore,
SM90, SM100, SM107, SM120, SM12x, gfx950, gfx1250, MI350X, MI355, B300, SYCL, Battlemage,
EPP, endpoint picker, WVA, workload variant autoscaler, HPA, GKE, OpenShift, Grove, LWS,
TENT, GDR, GPU Direct RDMA, TensorCast, kvpress, KVCache-Factory, parallax, xllm, rtp-llm,
chitu, MTPLX, ds4, sonar, Inkling, DSpark, Speculators, ThunderAgent, AIPerf, mocker,
Genesis Open Models, Unsloth, QAT, Q2_0, TQ1_0, IQ1_M, Helion, FBTriton, nvmath-python
<!-- 2026-08-08 第二轮新增（查证过的，含判定"不值得跟"的，避免明天重复发现） -->
HPC-Ops, Dynamic Attention, SpecForge, SpecBundle, SGL-Diffusion, AR+DiT, Miles, RadixArk,
BCG, breakable CUDA graph, PCP, prefill context parallel, TGV, Marlin, MXFP4 Marlin,
MNNVL, CUDA VMM, Ulysses, sequence parallel Ulysses, barge-in, MOSS, MOSS-TTS-Realtime,
Higgs TTS, SANA-Video, Cosmos3-Nano, MiniMax H3, Gemma 4, Qwen3-Omni, DeepSeek-V4 Flash,
Kimi K3, Inkling, OPD, on-policy distillation, sglext_spec, agent-aware KV cache hints,
Reasonix, DeepSeek-Reasonix, airllm, vllm-ascend, ai-hub-models, gfx1030, V620,
TencentDB-Agent-Memory, scheme-based quantization
<!-- 2026-09-22 新增（查证过的，含判定"不值得跟"的，避免明天重复发现） -->
DeepJIT, DeepSelect, colibri, turbo-fieldfare, expert streaming, VibeServe, BaseRT, ANEForge, ANE,
InferenceX, HyperQwen, Gewell, Splash Engine, unalloc, AISimulate, AIConfigurator, KVBM,
HiSparse, HiSparseConnector, Engram, mHC, Mega-mHC, Fast Start, ipc_cache, weight cache daemon,
Gumbel-max, Aaronson-Gumbel, watermarking, TransferEngine, Mooncake Conductor, NVIDIA Data Direct,
GDN, gated delta net, PrimTS, XQA, Sage attention, SiTU, cake_gdn, Cake, radix top-k,
SVDQuant, Lamport all-to-all, QSA, PDL, DCP MLA, split-KV, ReplaySSM, Chord, Humming,
FP4, BF16, W4A8, JIT, TCP, OOB, DFS, TP2, AMX, DSV4, DSV4.1, NVL72, GB300 NVL72, Vera Rubin, SM107,
MiMo, XiaomiMiMo, MiMo-V2.6, Qwen 4, K2-Horizon, GLM-5.3-Flash, Nanbeige, Bailing, Cohere Compass,
HunyuanImage3, FastH3, VSA, Cosmos3, Audex, MiniCPM-o, Fun-ASR,
RSI, RRSI, Harness-Zero, Jev, jevals, Jev-Mem, ARI, NER, IER, LPX, Halo, cuTile Rust, staircase,
SLEM, KV-COBRA, H-Spec, SPECTRA, Complex KDA, AWE, tree-structured speculation, oMLX, tokenizers v1,
TinyTorch, TensorRT Multi-Device, TensorRT Edge-LLM, ThunderKittens, FA4, FlashAttention-4, MXFP8 FA4
<!-- 2026-09-24 新增（查证过的，含判定"不值得跟"的） -->
HySparse2, KV Bridging, YOCO, KV Reuse, MiMo-V3, InstinctFlash, Jetson Thor, LingBot, LingBot-VA, LingBot World,
ModelExpress, MX, InstantTensor, ModelStreamer, HW-agnostic layers, flat models, USE_HW_AGNOSTIC, vllm-metal,
DPara, PSD, parallel speculative decoding, WISE, working-set inference, EQB, LEI, DeltaS, MicroQonv, CGLA, IMAX,
BitNet, SeedVR2, MammothModa2, SenseNova, SenseNova-U1, EAGLE3, MiniMax-H3, MSA, AURA, DuplexOmni, EGM,
AttnRes, PLE, hyperconnection, Petit, cdna5, MoRI, k8s-aibom, OrcaRouter, Flagos, zentorch, HRM-Text, Mimir,
Mercury 2.5, Lemonade, Antigravity SDK, LensVLM, FLUX 3 Action, CLM, Contrastive Language Models, EngramBuffer,
DeepEP V2.5, EPv2, WhatWorkedBench, SWE-Serve, FP32, VAE, NCCL, SWA, RNG, RAG, NUMA, SHM, FC1, TP8, CKS, GCC,
A3B, MMVQ, fp16, SOC
<!-- 2026-09-27 新增（查证过的，含判定"不值得跟"的） -->
MRV2, Model Runner V2, DiT, Code2Wav, MMA, TMA, SamplingParams, SageAttention3, FWHT, LFM2, LFM2.5-VL, LFM2.5-VL-DSpark,
RTX, SM110, SM120, Quail, AI-SQL, KV-aware join-order, left-deep join, MIS, Multi-Item Scoring, Score API, decision model,
prompt lookup decoding, n-gram cache, Overspill, FreeToken, DFlash2, TreeCore, Rust TreeCore, kv_snapshot, cache-aware peer bootstrap,
Model-Optimizer, ModelOpt, nobodywho, WeKnora, mobile-mcp, KEDA, LMetric, SenseNova-U1-A3B-MoT, Pi0.5, Kimi-K3 SiTU, per-token alpha
<!-- 2026-09-28 新增（查证过的，含判定"不值得跟"的） -->
Qwen4Exp, qwen4_exp, host_file_gather, PLE embeddings, CosyVoice3, HiFT, RPC, DAX, device-DAX, Optane PMEM, E2E, VRAM,
Naive-N0.5-Flash, NaiveAI, SWA-DSA hybrid, Masterless Rust Store, managed weight group, hylink, Hygon DCU, DCU, TONE,
EVS, Nemotron Super 3.5, DiffKV, BR166M, MemCache, MLU, Iris, TIRx, cudnn frost MoE, FPM, Global View, Ming-Image,
Higgs Audio v3, ZONOS2, XPUGraph, LocateAnything, Moss-TTS, static chunk ramp, CUDAGraphManager, MOPD, BC-250,
Swift 1.5, Muse, Nonobench, zen CPU SDPA, platform-owned RoPE, distributed Triton autotune, rank-skew calibration,
AlphaMoE NVFP4, cake_msa, cake_vsa, Q4SP, TurboMind C++20, checkpoint-engine, symmetric-memory LM-head all-gather,
piecewise CUDA graph prefill, Dlinfer, BuildSpec
<!-- 2026-09-29 新增（查证过的，含判定"不值得跟"的） -->
RLVR, P2P, EPLB, OpenEngine, openengine.v1, KvSessionRef, OPSD, MoRIIO, int32, HIP, GEMM2, DisaggregatedSet, ECR, TokenCast,
LSPD, JEPA, VLM, WAM, FullAttn, MALA, MassAlloc Attention, DPO, OpenShell, MoonEP, UltraEP, EPBuffer, EngramBuffer, PPBuffer,
BucketBuffer, bucket collectives, DeepJIT, lb_prefetch_weights, System One, DiffusionGemma, structured-read, openjev, Tetra,
Leech-lattice, Golay trellis, WavePP, Cartridges++, SANTA++, KV-streams, Telescopic LM, Foil, looped MoE, PRISM, PrimsTS,
Petit Gluon MegaMoE, bounded replay, OmniTyper, sleep-mode offload, TRTLLM_MTP_TAIL_TRIM, TRTLLM_CACHE_DIR, Holo4, ESP32 BitNet cluster,
Nemotron-Labs-3-Competitive-Coding, ToMoE v2, Ornith-1.5, Inferact
<!-- 2026-10-01 新增（查证过的，含判定"不值得跟"的） -->
LTX, LTX-2, LTX-2.5, BGMV, WebGPU, @huggingface/kernels, webgpu-kernels, TTL, CTA, GEN, TRTLLM-GEN, MHA, SGD, DP-SGD, TypeSafe, CEO, GLM5, GLM5-Next,
DGX, DGX Spark, Magnitude, Galahad, Taliesin, Blaise, ThunderEP, KVTether, Herschel, WUSH, WUSH-KV, UBTree, RATIO, Inference Auctions,
Loop Scaling Laws, looped MoE, Fork-dLLM, GrammarRL, Ascend 950, dav-3510, DeepGEMM-Ascend, DeepEP-Ascend, FlyDSL, KCP, MITO,
F1 cache reuse, agentic routing preset, x-dynamo-disable-caching, Spyre, Torch Spyre, CRCR, cuObject, SCADA, HSTU, Kumo Tabular,
TensorRT Model Connect, NeMo Relay, Modal Clusters, AutoDeploy, Helix, Helix speculative verification, YuE2, Ming-Omni-TTS,
Cosmos3-Multiview, res_multistep, Strix Halo, llama-halo-hybrid, FastFlowLM, Ryzen AI Max 400, Victoria, Maple, Qwen3.8-Flash-Next,
Nemotron 3 Diarization, NemotronH Omni, AOSC, PyTorch stable ABI, warp specialization, gemm_blockscaled, DFlash, ThunderEP,
Strata, Spotlight, Percepta, DwarfStar, DwarfStar 4, STP, single-token prediction, Nimble, Nimble decision model, /v1/systemone, /v1/decisions, Decisions API,
TLX, Triton Low-level Extensions, Jagged Flash Attention, 4over6, Four Over Six, MoE-CORE, ePACT, LoopCD, VETO, LLM2Jev, block-causal attention,
Motif-3, Motif-3-NVFP4, UMBP, Unified Cache, KVCM2, modeling_v2, MegaMoE, Rubin GenPhase, Kimi K3 AttnRes, FrogNano, UnifoLM-WLA,
EOS, NaN, PVC, CNN, ICL, CTX
<!-- 2026-10-07 新增（查证过的，含判定"不值得跟"的） -->
DGD, DGDC, DGDR, DynamoGraphDeployment, AgentX, AgentX draft slot, EmbeddingGemma, EmbeddingGemma2, IoT, MLP, MSVC, UNREAL, DCR, NeMo-DCR, SSR,
Sparse Segment Reduction, MetaInfer, VibeQwen, Sammie, LiLiCorr, Lachesis, HBF, High-Bandwidth Flash, SlimWise, ECO, AFD energy, HLA, Hybrid Linear Attention,
PHBA, Prefix-State Hybrid Block Attention, TRACE, FP4 RL rollout, DySCo, LQEC, DIPrune, vllm preload, weight-cache daemon, vllm snapshot, CRIU,
Mega-Gate, --max-num-active-seqs, --trust-request-mm-kwargs, Humming, K2 Horizon, MoVA, pplx-decider, PLaMo-3, XIELU, Mistral Large 4, Octop,
AICR, Together Link, FBTriton, frozen-predecessor KV takeover, lease-safe takeover, ThunderAgent, Cosmos3 attention, Prims-TS, cuDNN auto backend,
EPD receive pool, HiSparse ROCm, Lookup-table LM
<!-- 2026-10-08 新增（查证过的，含判定"不值得跟"的） -->
LiquidAI, d1, d1-3B, d1-omni-600M, CRTC, concurrent radix tree compressed, OpenCode, PyNvVideoCodec, LayerNorm, PRO, RTX PRO 6000, StepFun,
PTO, GELU, Engram, EngramEdit, HBM, NVHBM, GLA, GDN, hipFILE, AMD Infinity Storage, ROCm 10.1, PageBroker, DLoop, STEPQuant, ResidualQuant,
EncBank, CoMem, YANchor, Kernaut, Kernel Autoresearch, TR-PTQ, RLT, Recurrent Looped Transformer, Cake, unified-memory pool, fused draft KV,
Rubin, SM107, sm_107a, Lamport A2A, MNNVL, GDP decode, MUSA, Hexagon, cmpunlocker, CMP 170HX, DFlash 2, Ternary Bonsai 2, Kandinsky 6.0
<!-- 2026-10-09 新增（查证过的，含判定"不值得跟"的） -->
QKV, OpenAPI, MLLM, THP, Transparent Huge Pages, PersonaPlex, RGB, QoS, AI QoS, CCCL, ViSkill, SpaceCast, SpaceCast-Bench, SparseDecoding, TokenRouter, LEGO,
SparseEngine, Chain Cache, Prefix-Cache Pruning, KvHint, Session-Prefix Indexer, programmatic KV cache, session_id, ThunderAgent scheduler, SanSi, System 1.5,
typed decision model, InfiLoop, VFold, Universal Attention, DiffuPlex, CARE, Mole, LiteTopK, KV cache lending, Red-green watermarking, Apertus 1.5, Saluki,
Halogen, Mellum2.1, mooncake-hkvm, Mooncake Conductor, FastH3, gfx1250, PrimTS MLA prefill, HyperQwen, torch-spyre, PrivateUse1, Granite 3.3, MC-Sparse, V-CoLA
<!-- 2026-10-10 新增（查证过的，含判定"不值得跟"的） -->
DYN, GEMV, NoF, NVMe-oF, SPDK, DCGM, POC, GSQ, RCO, GSQ-RCO, Gumbel-Softmax Quantization, Riemannian Constrained Optimization, Basalt, .basalt, NInfer,
ML Drift, LiteRT, tensor virtualization, Locality Domains, locality-aware MoE, green context, CUDA 13.4, MLPerf Inference v6.1, Velo, velo-ucx, ucx-rs,
response plane, DYN_RESPONSE_PLANE, PDMux, FDFO, decision-guided compaction, Pi compaction, galahad-kv, H2O-Lightning-4B, JevBench, Laya, GLiNER2.5,
--enable-structured-decisions, Qrita, dots3-note-prev, Kpool, CSA2, MoEEpLayer, NCCL-EP, NIXL-EP, MegaMoE SM107, dual-cache, GLM53-NoPE, hixl, MACA,
IBGDA, PTODSL, aibin, two-phase grouped prefill, Mamba prefix checkpointing, MC_RDMA_SIGNAL_INTERVAL, selective signaling, sparse KV offloading, open-slopware,
Qwen-Image-2.1-Turbo, Youtu-Parsing-Omni, LightOnOCR-3, GLM 5.3 Flash, Granite 4.2, Boogu-Image, DreamZero, SANA-WM, EasyMagpie, LLaDA2-Uni,
Full-Duplex MRv2, TPU7x, Cognition SGLang fork, Inferact MiniMax-M3-EAGLE3
<!-- 2026-10-11 新增（查证过的，含判定"不值得跟"的） -->
FC2, IKL, IKL-569, MarkovSampleStep, markov draft head, MegaGate, Mega-Gate, KVCR, KVCR HiCache hints, kv_hints, RESIDENT_BLOCKS, resident blocks,
snapshot-based retraction, retraction image, snapshot pool, slot-state blob, KV parallelism, kv-parallel-size, QCP, MLA 2, tokenspeed-mla 2.0, RATE pruning,
redundancy-aware token pruning, image-pruning-rate, mm_nvfp4_lora, mm_fp8_lora, quant LoRA GEMM, svdquant, MMQ, ggml_mul_mat_a8, int8 tensor-core MMQ,
DeviceTransferService, IBGDA route, collect_stage_metrics, Moshi, Hibiki, request-local Philox stream, swap_blocks_batch, shutdown_weight_transfer_engine,
frontend admission, freeze-gc-after-init, VMM CUDA IPC, KV cache manager V2, NIXL 1.5, DSpark adaptive verification, mixed-chunk, check_decode_mem,
open-jet, spec-cycle megakernel, ForgeMegakernel, club-170hx, MegaQwen, backburner, split prefill, dsv41-flash-offload, staged-DMA prefill, Infernix,
ninfer-offload, kyojin, ExLlamaV3, EXL3, gfx1151, MiMo-V2.6-Flash, Strata-DualGPU, strata-mlx, oQ4E, Lightning MTP, SSD N-gram Offload, MoE upcycling,
dense-to-MoE, Swift 1.5, BC-250, MegaCapybara, PS5LM, Foundry Adapter, K-EXAONE, FDB, 6.1-Sol, MiniCPM-V 4.7, Pi0.5, ReplaySSM
<!-- 2026-10-12 新增（查证过的，含判定"不值得跟"的） -->
UPDATE, GUI, Project Maya, Maya-S, Maya-M, Maya-S24, probabilistic MTP, UltraQuant, ARK, AutoRound ARK, Glm4MoeLitePlusPlus, HybridEP,
device-sync shared-memory carveout, USRBIO, LSA, GIN, NCCL device route, ADXL, Ascend Direct, MindIE-SD, FIA, EQBSA, AesCode, Whistle,
Decision 3.0, Jev Decision Index, LLMxRay, SoloQ, dLLM quantization, PreSTO, PowerMH, power sampling, GraphDecisionBench, VoxCPM2,
cake_qkv_norm_rope_exchange_overlap, cake_dsa_indexer, pull-style MegaMoE, eplb-max-rebalance-count, Reflection AI, AirLLM, overfit inference engines
<!-- 2026-10-14 新增（查证过的，含判定"不值得跟"的） -->
FMA, Fast Model Actuation, KEDA, scale-from-zero, VisualGen, tp_layout, token-sharded tensor parallelism, MPI, Open MPI ob1, TP4, ATOM, MoRI-IO, MoRIIO, AVX, AVX2, DoubtLess, CoT, ReVeR, GRPO,
A2B, LFM2.5-24B-A2B, FastEEP, intra-instance elastic scaling, DynamicEPLB, DoSA, Dots Sparse Attention, KSA, Kwai Summary Attention V2, MultiAlloc, SP2ec,
CSNB, Cauchy-Schwarz Norm Bounds, SDC, ABFT, PureKVA, Iris, Lamport all-reduce, MI455X, gfx1250, gfx950 Gluon, cake_msa, MSA Top-K, SiTU experts, Motif-3, Motif-3-NVFP4,
KDA RecoverSSM, use-replayssm, Glm5NextProcessor, Jeva, VideoJev, Jev-Guard, Jevcrawl, Consus, MaixStation, Lemonade, Spyre Inductor, Tremulant, Orrery,
resident-weight recovery, warm standby, Fault-Tolerance Framework, passive Mooncake store capacity, KVCS, tebench, tier-based sleep, Level-Zero IPC, Full-Duplex-Bench,
ATOMesh, SGLang-ATOM, vLLM-ATOM, Smart Turn VAD, PiD, Pixel Diffusion Decoder, Chatterbox TTS, Granite Switch, vllm-rs, Rust Frontend, Run:AI Apache-2.0, airllm, cursor plugins
<!-- 2026-10-15 新增（查证过的，含判定"不值得跟"的） -->
CIFAR, MiB, SIMT, SIMT VF, OCP, OCR, MRI, MIMIC, KVP, SM89, DisaggregatedSets, CriticOPD, LatentLoop, looped MoE, Radiance, vllm-radiance, .rad, RDNA4, gfx1201, R9700, R9600D,
Telperion, TelperionAI, GLA-g2, Grouped Latent Attention, MLA retrofit, token-rush, ninfer-4090, E8 4-bit KV, Nemotron Bolt 3.5, Step-5-Preview, Ling-3.1-flash, Tessera-27B-B-CJK, Sabi-Noema,
NIXL push connector, push-based KV transfer, online acceptance estimator, GDN MMA, spec-draft-n-ubatch, Breezeblue-tts-2
JSSA, Joint Subspace Sparse Attention, Latent Compaction, KVZip+, TreeSpark, ReaDy, KV4-RL, The COUNT, NatScale, SpectrumQuant, NixlPushConnector, Biren, Moore Threads, E/P/D, E/PD,
INT4 QuickReduce, singleflight cold read, fp4_allreduce, NVFP4-transport all-reduce, Nemotron 3.5 Bolt, Nemotron 3.5 Bolt E4B, Responses API Foundations, PipelineEpdPrefillAdmission
<!-- 2026-10-16 新增（查证过的，含判定"不值得跟"的） -->
OOT, out-of-tree, A12B, A9B, A6.8B, MLE, MPT, market-based post-training, AutoSFT, MaLoW, HyperNetwork, CIM, compute-in-memory, ABNAT,
Muse Spark, Muse Spark Open, Muse Glimmer, Muse Model License, latent MoE, pooler/unpooler, Reflection Beam, Beam, Kolibri, Kolibri 1, Ling 3.0, Ling 3.0 Flash, BailingHybrid,
Nemotron 3.5 Super VL, Nemotron-3.5-Super-VL-120B-A12B, Nemotron-3.5-Lightning, MAI Code, MAI Code 1.1 Flash, maion-coder, Mistral Medium 3.5, Timestral, Jais 3, FLUX.3 Klein,
UnlimitedOcr, R-SWA, Reference Sliding Window Attention, UltraBERT, MOSS-Transcribe-Diarize, voxtral-realtime, mtmd_audio_stream, Granite Switch 4.1, aLoRA, Activated LoRA,
cuDNN Frost, Frost MoE, CudnnFrostNvfp4Config, cake backend, cake_fused_moe_prepare_workspace, PowLU, Prims-TS GEMM, tmem_overlap, DFlash V2, block verification, TITO, R3,
Rollout Routing Replay, RDC, Router Drift Control, TorchTPU, SGLang-TorchTPU, TPU v7, moe-cache-mib, MoE expert cache, common_chat_session, port 9931, Symphony parser,
jaccl, Thunderbolt 5 RDMA, MLX distributed, M5 Ultra, MTIA, affinity, AFF_ALLOW_NRANK, Janas, Janas-LLM, capy-flash, ninfer-tp2, FP16 partial sums, TP partial-sum rounding,
ALoDLM, ALoDLM-8B, adaptively looped diffusion, nano-vLLM, QUASAR, QUASAR-QAT, QAD, quantization-aware distillation, Qwen3.8-Flash-Next-FP4-Local, Ternary Bonsai 2,
Prime Inference, Prime Intellect, BLHNC, LBHNC, block-major KV layout, SpecAgent, trajectory-level speculation, PN-Mix, pair-norm, Conditional Program, Gaussian trellis,
Close Enough is Nowhere Near, tolerable set, internal-state sharing, Speculative Forcing, LongLive, Lingbot-World 2.0, JevAgentHarness, AgentDecisionBench, AgentDecision-4B,
DecisionGym, Intern-Decision, EdgeWise, Hy-Memory, LCT, Losslessly Compressed Tensors, BitSparse, RoleQ, SIRS, TIPS, makespan bounds, GPipe homogeneity bias,
GDN MTP replay V2, KDA MTP replay, First-N/Last-N mixed-precision KV, KVCM V2, MemFabric, MemFabric Transport, striped object route, train-inference consistency, bitwise-consistent RL,
CSA2 candidate blocks, length-aware top-k, Iris all-reduce, MI450, gfx1250 MXFP4 MoE, AgentX PD recipe, unified cache external linker, monokernels, A5 explicit-state backend,
Expert LoRA, Pluggable KV Cache Data Types, routed experts return, DSV4 MegaMoE decode instance, Kimi K3 MI355X, DCP8, FlyDSL, Snapdragon X1, Adreno X1-45
<!-- 2026-10-17 新增（查证过的，含判定"不值得跟"的） -->
FA2, GeForce, ORL, On-Policy Residual Learning, dlmrt, residual context, entropy contraction, TPF, tokens per forward, LLaDA-2.1-mini, LLaDA2.1-mini, QwenDLM, QwenDLM-4B,
DiffusionGemma-26B-A4B, deepseek-recipe, DeepSeek-V4.1-Flash-1017, Beam-1.0, Beam-1.0-501B-A23B, SSMax, Scalable Softmax, NoPE, sandwich norm, depth-scaled residuals,
sigmoid output gate, FP32 router, BF16x3 GEMM, DFlash2, adaptive verification, latency_specialized, decode_backend, fast-track model optimization RFC, AI-usage trailer,
Tyger, Llmspeed, Hy-Memory-30B-A3B, Nemotron-Labs-Dory, Dory1.0-4B, MOSS-Image, GYRO, Gyro-GGUF, bodhi37, adaptive KV streaming, Zephon, RTX Spark, DMA-BUF,
Granite Switch Decision, decision_chat, prompt_cache_key, gvr v2, admission barrier, EngramStore, shared NVMe KV backend, AIMD congestion control, HRRN,
frozen-KV MTP, encoder-free text serving, MegaAttention, encoder bounded replay, SM8x GDN prefill, FP16-accumulate MMA, BGMV, QkvNormRopeExchangeOverlap,
Ming-TTS MLX, LTX 2.5 text-to-audio, MAGI-2, technology export catalog, HVX softplus, Mellum2.1 MTP
<!-- 2026-10-18 新增（查证过的，含判定"不值得跟"的） -->
GAIE, Gateway API Inference Extension, agentgateway, gateway_ab, Xolotl, Strata-DSV4.1, Strata-DS4, IndrasMirror, pipelined speculation,
heterogeneous device chain, PCIe SDMA, llama-cpp-rdna-boosts, sibling activation reuse, RadixValue, PageValue, suffix continuation insert,
deslop, CAKE deslop, oracle drafter, spec decode ceiling, FROST low-latency, frost_low_latency, FrostLowLatencyConfig, ue8m0_g32_inline,
fp8_dsv41_inline, inline-scale KV, footer-scale KV, Store reshard, KV cache reshard, ModelSemanticDomain, session_ids, num_serve_frontends,
KvCacheRetentionConfig, cold_tier_offload_min_priority, unified kv cache manager, DFlash unified KVCache, MonoKernel authoring guide,
natural checkpoints, junction cut, CacheBoundaryKind, b12x, clef-omni, EmbeddingGemma 2, MiniCPM-V 4.7, Nemotron 3.5 ASR, FlashKDA,
decoder_replay_trim_threshold, enable-hc-sp, response_template, hf tool parser, vllm download-kernels, preload-autotune, ultraquant_4bit,
MoE LoRA, lora_cutedsl, lora_triton, lora_marlin, triton_v2 LoRA, Kolibri-1, Fish Audio Drama 3, AutoTrust, AITER default
<!-- 2026-10-19 新增（查证过的，含判定"不值得跟"的） -->
DWDP, Distributed Weight Data Parallelism, DWDP8, Kapitsa, nace-ai, kapitsa doctor, recurrent-state checkpoint, ANE prefill, Neural Engine prefill, SonicBoom, Boom IR, HardenedLinux,
eidola, eidola-engine, salted prefix cache, byte-reproducible kernel build, CPU reference executor, PegaFlow, Intel Inference Microservices, Agens Engine, Agens Volundr, Volundr 32B,
Blockway, Agens-Volundr-32B-v1-Engine-16GB, session continuation, HybridAgent, Hybrid Reasoning Agents, HybridAgents, latent reasoning agents, Harness2, STROT, Strot, strot-ai,
IQ2_K, IQ3_K, IQ4_K, IQ5_K, IQ6_K, TensorSharp, TensorSharp Video Studio, TensorAgent, amber-8, AuroraASR, AuroraASR-1M, strata-nvfp4, sparkDash, cmp170hx-qwen38-flash-next,
Le Chonk, Mistral Large 4, DLite, history-free speculative decoding, CarryOn, continuation carrier, object-oriented context, Speculative Sampling, interactive video generation,
frozen vocabulary, 512-bit codes, embeddings-are-overpriced, LEV, looped decision models, DAGFormer, prelude-recurrent-coda, Sol-H3, LTX-2.3, Wan1.3B
<!-- 2026-10-20 新增（查证过的，含判定"不值得跟"的） -->
ComfyUI, headroom, headroomlabs-ai, PEFT, OpLog, OpLogApplier, SMG, tokenspeed-smg, LCM padding, OpenVLHarness, KronLSTM, Kronecker Delta Rule, TorchNeuron, torch-neuronx, NKI-lib,
adaptive eager mode, vLLM Neuron, dsx, dsx-2bit, DSX_ADAPT, berth, Maxwell, code execution model, CEM, proof gadgets, CompileIQ, Advanced Control File, ACF, booster pack,
helion-booster-pack, autotune_search_acf, sgl-nvidia-mega, sgl-amd-mono, SGLang Low-Latency Mode, NIXL EP, async preparation, Elastic EP near-zero downtime,
QCP, KVP, DCP, EngramPrefetcher, engram prefetch, moe_fence, decoder-swa-bounded-replay, radixshmem, RadixShmemStorage, KV checksums, kv_checksum, mxfp4_mla,
decode-to-prefill KV reuse, kv.fetch hint, ThunderAgent idle reservation, dynamicPD, dynamic P/D disaggregation, vllm-torchtpu, vLLM Torch TPU, llm-d-api-extensions,
llm-d-pd-utils, llm-d-prism, probabilistic admitter, turn-priority scoring, program-aware fairness, MNNVL two-shot, TokenGate, token-gated attention, ReAnchor, DScout,
Parallel Language Models, PLM, variational decoding, streaming generation, time-to-answer, Heartbeat Thinking, LatComm, latent communication, ECHO, Dynamic Depth Sampling,
SparkInfer, TensorFold, tqLLM, lynx-gt, hipfire, Lucebox, Paiton, fngine, LocalMaxxing, tinkerbox, d1-3B ANE, Ming-3.0-audio-flash, Ming-3.0-audio-tiny, MiniMax-M3.1-Flash,
North Micro Vision, Command A+, North Mini Code, Physis Same-Step, VibeVoice-1.5B, SenseNova-U1.5, HSDP data parallel, Voxt, adaptive-thinking, Tess-4.5-27B, CEMA-Router,
<!-- 2026-10-21 新增（查证过的，含判定"不值得跟"的） -->
DRAM, SiLU, MPS, CacheConfig, EAGLE-4, EAGLE-Harness, LlamaForCausalLMEagle4, low-rank candidate head, TreeRejectionSampler, KFlash, best-first tree verify, Gufo, Narwhal, role hot-swap, role-free fleet, open_rknpu2_lm_infer, RKLLM, RK3588 NPU, AKV, cache engineering, KV drop/repos, Token-Energy Law, AMTP, Adaptive Multi-Token Prediction, BitMTP, KPage, Specter, speculative expert offloading, Lafa, Large Flow Language Model, EdgeKernelBench, REMORY, residual memory tokens, Fisher-MoE, Less-is-MoE, OneStreamer, VideoChat3, DeepInfer, DEEPINFER_BATCH_INVARIANT, YoCo prefill truncation, SWA bounded replay, confidence-scheduled verification, mtp_varlen, cachedMoE, leCore, PlatformBiren, T-HEAD SAIL, index_k_tp_shard, latency_specialized decode, UMBPStoreConnector, prefix_affinity_weight, KV DC Relay, SubscribeServingLoad, Pylon, Stargate, DSpark online cost correction, enable-state-checkpoint-chunk-cut, prefill-graph-max-tokens 8192, Gluon decode megakernel, tagged mailbox, NVFP4 4over6 KV writer, Respan, SpyreCode, KTIR, AnyLanguageModel, Pocket TTS, Phonon, Intel Arc Pro B65, ISTA prefiller, Qwen3.8-27B-NVFP4-prefiller, MoE down-proj per-expert scaling, POST /tts, realtime transcription API, agency-agents, cursor/plugins
<!-- 2026-10-22 新增（查证过的，含判定"不值得跟"的） -->
FMHA, fused multi-head attention, AuxOutput, indexer replay, profile-based replay, KPool, CANN, asc_float2bfloat16_rn_v2, DeepEvolve, TraceForge, KVCompass, minimal perfect hashing, MPH, discovery plane, cross-region prefix cache, LES, Lookahead Expert Scheduling, llama.cpp-omni, MiniCPM-V 4.7, iPhone 18 Pro Max, VocabX, vocabulary specialization, macro tokens, sub-word layer, HAWK, GPU-NPU phase disaggregation, tensor-layout-aware RDMA buffer, UlaCache, unified logical addressing, PB-LRU, RISK-KV, selective KV reconstruction, cross-layer ridge regression, RCSD, SPARE, routing entropy, Flint, flint-40B-A2.5B, Recursive SI, Eureka Machine, mostly-local attention, 513-token sliding window, learned attention sinks, RFC 0002, ts-host, Rust control plane, ts-scheduler, ts-mooncake, Attention-FFN disaggregation, 8A+8F, Direct MegaMoE M2N, compact beam execution, VBWS, KV cache lending API, Modeling V2 target, KV cache manager V2, Python KV cache transceiver, progressive host tier filling, cold-page compression, ragged DSpark verification, DataManagerV2, Tiler/Block, selective signaling, CQE, soft-pin, EGM-backed Mooncake Store, MooncakePullConnector, LAW, Loopholing All the Way, UDLM, Looped Uniform Diffusion, 2-bit draft + residual verifier, Kitten-TTS 2, 1.58-bit TTS, Gyro-S, Gyro-M, GPU roles Main/Helper/Off, rx6000 engine package, answer speed, Granite Speech 5.0, MemT-1.0, OvisOCR3, Sage-A1.5, NVIDIA Sentry, inference-time abliteration, HTI, half-tile interleaved, AOTriton 0.14.2b, FlyDSL attention, Kumo Relational, TorchTitan TitanRL, Modal Dojo, nobodywho（llama.cpp 封装 SDK，老仓，不跟）, headroom（agent 上下文压缩代理，应用层，不跟）, cursor/plugins（不跟）, ComfyUI（不跟）, QSA mask fused op, Nemotron-3 Ultra, MiniMax-M3 decode index scoring, Boogu-Image, frozen-KV drafts, npu_memcache, Engram shards over NVLink, A5 explicit-state, C4 state
