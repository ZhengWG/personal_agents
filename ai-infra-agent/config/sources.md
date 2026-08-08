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
`huggingface/text-generation-inference` · `ggml-org/llama.cpp`
Omni / 多模态：`vllm-project/vllm-omni` · `sgl-project/sglang-omni`
Kernel / 编译：`flashinfer-ai/flashinfer` · `tile-ai/tilelang` · `tile-ai/TileRT` ·
`deepseek-ai/DeepGEMM` · `deepseek-ai/TileKernels`
KV / 通信 / 并行：`kvcache-ai/Mooncake` · `deepseek-ai/DeepEP` · `deepseek-ai/DualPipe` ·
`deepseek-ai/3FS`
投机解码 / MLA：`deepseek-ai/DeepSpec` · `deepseek-ai/FlashMLA` · `lightseekorg/tokenspeed`
生态：`huggingface/transformers`

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
- Aphrodite Engine（`aphrodite-engine/aphrodite-engine`）— 2026-07-12 — fork vLLM，社区量化格式/采样器长尾覆盖最全
- Modular MAX / BentoML — 2026-07-12 — 另两个正在起势的 serving 栈，先挂观察
- Bessemer「AI Infrastructure Roadmap」— 2026-07-12 — VC 视角 infra 前沿地图，季度性对照盲区
- Eval-infra：Braintrust / Judgment Labs / Bigspin.ai — 2026-07-12 — 推理下游的语义 eval/生产监控层，正在独立成形
- OmniRoute（`diegosouzapw/OmniRoute`）— 2026-07-13 — AI 网关，231+ provider 一站接入 + 级联 token 压缩，9k+ stars 增速快
- kvcached（`ovg-project/kvcached`）— 2026-07-13 — 虚拟化弹性 KV cache，动态 GPU 显存共享
- LMCache / Tensormesh — 2026-07-13 — KV cache 层独立商业化，$20M 融资 + AMD/NVIDIA/CoreWeave 战投
- llm-d-kv-cache（`llm-d/llm-d-kv-cache`）— 2026-07-13 — llm-d 生态下跨节点 KV-cache-aware 路由
- Agentic workflow-aware serving 子领域（Helium/Nalar/Cortex/HexAGenT/Pythia）— 2026-07-13 — 把 agent 工作流建模为查询计划/DAG 调度，论文扎堆出现
- ParoQuant（`z-lab/paroquant`）— 2026-07-14 — 学习式 pairwise-rotation INT4 量化（ICLR 2026），精度逼近 FP16、速度接近 AWQ
- HF Kernels Hub（huggingface_hub v1.10.0+）— 2026-07-14 — GPU kernel 的包管理器式分发，已接入 TGI/Transformers
- TurboQuant+（`ggml-org/llama.cpp` Discussion）— 2026-07-14 — Walsh-Hadamard 旋转极坐标量化，KV+权重极限压缩
- BanaServe（Software: Practice & Experience 2026）— 2026-07-14 — 统一 KV cache 管理 + 动态 module 迁移的 MoE-aware 分离式 serving
- TraCT（arXiv:2512.18194）— 2026-07-14 — CXL 共享内存做 rack-scale 分离式推理 KV 传输底座，替代 RDMA，claims 2.6x TTFT 降低
- MTPLX（`youssofal/MTPLX`，另有 `dbuck/mtplx` 镜像）— 2026-08-08 — Apple Silicon 上跑模型自带 MTP 头做投机解码，无外部 draft model，temp 0.6 下 2-3x decode TPS；MLX fork + 自定义 Metal kernel
- ds4（`antirez/ds4`）— 2026-08-08 — antirez 写的 DeepSeek 4 Flash/PRO 本地推理引擎，一套代码覆盖 Metal/CUDA/ROCm，单模型专用引擎路线
- kimi-k3-in-c（`FareedKhan-dev/kimi-k3-in-c`）— 2026-08-08 — 2.78T Kimi K3 用纯 C99 在单 CPU + 8.24GB RAM 上跑推理，无 BLAS/框架/GPU，极限权重流式加载的教学级参考
- kvpress（`NVIDIA/kvpress`）— 2026-08-08 — NVIDIA 官方 KV cache 压缩方法库，和 `Zefan-Cai/KVCache-Factory` 一起构成 KV 压缩的方法评测底座
- parallax（`GradientHQ/parallax`）— 2026-08-08 — 分布式 serving 框架，主打「用异构/家用设备拼自己的推理集群」，和 petals 一脉但面向 2026 的 MoE
- xllm（`xLLM-AI/xllm`）· rtp-llm（`alibaba/rtp-llm`）· chitu（`thu-pacman/chitu`）— 2026-08-08 — 三个国产推理引擎，主打国产/异构加速卡适配，先挂观察看是否持续出料
- AFD（Attention-FFN Disaggregation）— 2026-08-08 — 把 decode 阶段的 attention 与 FFN 拆到不同 GPU 池，PD 分离之后的下一级拆分粒度（arXiv:2605.28302、2601.21351）；NVIDIA 收 Groq IP 的技术动机
- HPC-Ops（`Tencent/hpc-ops`）— 2026-08-08 — 腾讯混元 AI Infra 开源的推理算子库（Dynamic Attention / Fused MoE / GEMM / 采样 / 通信计算融合），已在腾讯大规模生产 serving 落地，且已接入 SGLang；对标 FlashInfer 的第二个「厂商级算子库」入口，值得持续跟
- SpecForge（`sgl-project/SpecForge`）— 2026-08-08 — SGLang 的投机解码**训练**栈，v0.3.0 把 target/draft 训练解耦成分离式 + 共置两种模式，并放出 SpecBundle 开源 draft 模型系列；投机解码从「推理技巧」变成「要配套训练基建」的信号
- DeepSeek-Reasonix（`esengine/DeepSeek-Reasonix`）— 2026-08-08 — 终端 coding agent，卖点是「围绕 prefix-cache 稳定性做工程」；应用层，但反映 agent 侧开始按推理引擎的缓存特性反向设计，观察是否形成模式
- vllm-ascend（`vllm-project/vllm-ascend`）— 2026-08-08 — vLLM 官方社区维护的昇腾硬件插件，国产卡适配的主入口之一，先挂观察
- Miles（SGLang 生态的 RL / 训练框架）— 2026-08-08 — 与 SGLang rollout 深度绑定，Day-0 模型支持、MXFP8/NVFP4 RL 都从这里出；不是推理引擎但强影响推理侧精度格式，挂观察

> 排除记录：`dphnAI/sonar` = Aphrodite Engine 改名，**不是新项目**，别再当新发现（2026-08-08 查证）。

## 已提升 / 已淘汰（留痕）

> 提升：`- <源> — promoted <日期> — 已加入 repos.json tracked`
> 淘汰：`- <源> — dropped <日期> — <为什么不跟了>`

- LMDeploy（`InternLM/lmdeploy`）— promoted 2026-08-07 — 已在 repos.json tracked 中

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
