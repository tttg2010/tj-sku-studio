# v1.7 执行与验收

> 历史版本，仅用于回看 v1.7 运行记录。新任务请使用 [production-v18.md](production-v18.md)；v1.8 增加原始像素合成、独立蒙版复核和精确尺寸门禁。

适用：主图/附图/A+ 套图、反光或多孔材质抠图、场景合成、局部返修和 A/B。这些是生产约束与本地验收工具，**不是自动修图引擎、视觉相似度模型或平台审核保证**。不发起付费请求也可策划、建清单和运行检查。

## 1. 从测试问题到交付约束

| 发现的问题 | 必须采取的动作 | 阻断条件 |
| --- | --- | --- |
| 金属高光/细杆误透明 | 在原始像素网格独立标注不透明保护区，黑白彩底预览 | 保护区丢失；孔洞填实；轮廓缺损 |
| 加了阴影仍像贴上去 | 先匹配源图机位、支撑/悬挂、尺度、光源、遮挡 | 悬浮、穿模、错误受力或不兼容机位 |
| 白底商品缩放加字充当卖点 | 每槽位写买家问题及“隐藏文案后看见的证据” | 仅有标题、色块或整件缩略图 |
| 主附图与 A+ 高度重复 | 全套两两比较五个分镜轴；逐张说明新增证据 | 同成品底图换字；无新增问题/证据 |
| A+ 只有方案未生成 | 冻结角色数量、尺寸；核对实际文件及 QA 哈希 | 少任何已约定模块，或只有提示词 |
| 耗时长、自动报告误称通过 | 首稿/完整交付分开计时；具名逐图复核；限次提交 | 超预算继续付费；缺视觉复核却报完成 |

先选一张风险最高的材质/互动样张。蒙版局部、全轮廓和物理融合通过后再扩展；不要先批量生成再发现同一错误。可复用已批准的**商品原始抠图、细节裁切、字体规范**，不能把同一张**成品场景图**重复当作多个不同卖点。鞋撑装入鞋子、吊床承重、服饰穿戴等，不能仅凭未使用状态抠图臆造变形；需要相符使用参考，否则换能证明的方向。

## 2. 材质蒙版保护（不是抠图工具）

先由可靠抠图工具或人工建立 alpha，再从**原图独立标注**已确定不透明的内部区域 `opaque-core`；实际孔洞可另标 `keep-open`。这些标注只覆盖确定的内部，不用于声明全轮廓正确。没有可信标注时，保留草稿并说明缺口，不用 alpha 自己生成自己的“正确答案”。

- source：RGB/RGBA/L/LA 静态原图；alpha：L 或 1 模式。三种蒙版与原图尺寸、EXIF 方向必须一致，不自动缩放对齐。
- core/keep-open：L 或 1 模式、只含 0/255；core 非空；二者不能重叠。250 以下的 core alpha 或 5 以上的 keep-open alpha 会阻断。
- 工具会保守拒绝与 alpha 阈值结果完全相同的 core，但不能识别所有伪独立标注；修改/侵蚀后的 alpha 副本仍可能绕过，必须核对来源。
- 检查并不修复 alpha，也不根据白色或亮度猜材质。RGBA 原有透明度会参与有效 alpha，不会恢复原本透明像素。

```bash
python3 scripts/matte_guard.py \
  --source /project/product/source.png \
  --alpha /project/product/masks/alpha.png \
  --opaque-core /project/product/masks/opaque-core.png \
  --keep-open /project/product/masks/keep-open.png \
  --report /project/product/qa/matte-01.json \
  --preview-dir /project/product/qa/matte-preview-01
```

`keep-open` 可省略，但必须另看孔洞。报告父目录预先存在；预览目录必须是新路径。报告与预览均不覆盖旧文件。输出黑/白/洋红/绿色/棋盘底诊断图，逐张在原始分辨率检查高光、细杆、孔洞、白边和残留背景；再对照原图检查**未标注区域及全轮廓**。无局部违规时仍为 `draft`，不是最终放行；不能以这份报告替代成图对比。

## 3. 套图清单与执行顺序

复制 [../templates/production-manifest.json](../templates/production-manifest.json) 到项目目录；模板仅示范“一主图、一附图、一 A+”，按用户约定增减槽位。模板中的路径、时间、商品事实和 `null` 不是合格数据，必须用真实证据替换。相对路径相对**清单文件所在目录**解析。

1. 冻结原始素材清单（最多 9 张）、商品身份/未知项、已证实卖点、角色张数及尺寸。用原图 SHA256 保存输入身份；不要把输出重新加入输入。
2. 每槽位填写 `question/camera/composition/interaction/evidence_style` 五个轴，`visual_proof` 写去掉宣传字后仍能看见什么，`scene_fit` 写机位、支撑、光线、尺度和遮挡。附图/A+ 禁用 `hero` 充数。允许 `macro/mechanism/sequence/scale/use/bundle/supported_comparison/brand_story`，但标签本身不证明卖点真实。
3. 运行 `plan`，再对整套分镜人工去重。正常槽位两两至少三轴不同；即使标签不同，实际证据重复也退回。先通过一张风险样张。
4. 每次付费提交前运行 `next --slot ID`，另外运行原有 `preflight`。`estimated_next_seconds` 必须依据所选通道近期耗时，不能把示例默认 180 秒当服务保证。`next` 不会发请求；当前客户端也不会自动读取清单，执行者必须遵守门禁。
5. 一提交就写入该槽位 `attempts`：唯一 `request_id`/可得的 `task_id`、`submitted_at`、模型及状态；不写 headers、key、Base64。新提交算尝试，轮询原任务不算；一次 n>1 请求给每个涉及槽位记录同一 request_id，并在账务核对时按唯一 request_id 去重。为明确预算，套图默认逐槽位单图提交。
6. `submitted/unknown` 未结算前不再提交；每槽位最多初次加一次付费重试。超时/5xx 不说明未计费；先查询并保留原请求。失败后可转本地合成/补素材，不无限重抽。
7. 最终输出放同一商品文件夹，`generated-...` 命名。逐图 `image_qa.py`；记录报告路径、目标尺寸、真实成品底图 `base_asset_id`。不要给同一成品底图随意改 ID 冒充不同场景。
8. 对照所有相关原图，以原始分辨率查看每张成图并查看整套联系表。具名填写七项 review checks 及具体观察笔记、真实时间，并将所看文件的 SHA256 记入 `review.output_sha256`；未查看填 `null`，失败填 `false`，不要复制全 true。`finished_at` 必须晚于最后复核。
9. `delivery` 核对数量、实际可解码文件、尺寸、重复文件、当前输出哈希及具名复核。缺文件/身份失败为 `blocked`；缺复核为 `draft`。仅完整通过才可说整套完成；仍不是平台已审核。

```bash
python3 scripts/production_guard.py plan --manifest /project/product/run.json
python3 scripts/production_guard.py next --manifest /project/product/run.json --slot secondary-01
python3 scripts/image_qa.py --source /project/product/source.png \
  --output /project/product/generated-secondary-01.png \
  --report /project/product/qa/image-01.json
python3 scripts/production_guard.py delivery --manifest /project/product/run.json \
  --report /project/product/qa/delivery-01.json
```

报告使用新文件名，不能覆盖清单/原图/旧记录。自动筛查通过仍为 `draft`；delivery 的 `passed` 表示“本地文件与已记录的视觉复核均满足”，工具**不能验证观察记录是否真实**，也不计算商品相似度。修改成图后须重新筛查及视觉复核；旧 QA 或旧人工复核哈希不符均会阻断，缺复核哈希为 `draft`。不能只刷新文件 QA 或自动替换复核哈希而沿用旧观察记录。此处将约定成品要求设为全部交齐，比“完整率≥90%”更保守；缺失模块须经用户明确减范围，不能事后悄改计划。

## 4. 视觉验收与卖点证据

七项检查：身份结构、原始材质、抠图边缘、场景融合、可见卖点证据、文字/排版、无虚构声明。文案逐字核对批准原稿；OCR 缺失/空结果不是零错字。对照图必须是同等条件、有来源的实拍/明确示意，不能编造竞品劣质表现。纤维微距不能证明原生木浆，示意四层不能证明实际四层；需要对应产品资料及实物参考。

可采用固定人工场景评分表，开测前冻结样张锚点和评分人：

- 透视尺度、支撑接触、光影色温、边缘材质、遮挡景深，各 0–20，合计目标≥75；0 表示明显错误、10 有明显问题、15 基本自然、20 无可见问题。
- 贴图感 1=无、2=轻微、3=明显、4=严重、5=不可用，目标≤2；逐图记录观察原因。
- 光源方向匹配图数÷全部适用场景图数，目标≥90%；不适用项单列。不用主观总分掩盖悬浮、穿模、缺件、Logo 错误等硬失败。

## 5. A/B、局部修改与统计口径

**A/B**：普通槽位之外另加变体，设置 `variant_of`、`ab_variable`（copy/camera/composition/interaction）、`ab_change` 精确说明唯一变量，其他分镜轴和商品事实锁定。交两份实际渲染文件，同尺寸；不能只给建议，也不能代替缺失 A+。本工具只检查声明的一致性，实际画面仍需并排复核。无真实流量实验，不报转化提升。

**局部修改**：`run_kind=local_revision`，记录前一版本、请求的修改区域/文案及未修改区域对比；只修受影响槽位，不重跑整套。5 分钟计入本地合成、排版、QA/复核。需要新机位/重建几何是新的需求，先说明并经用户确认，不能事后改名剔除超时。

**计时**：开始于本次确认范围后进入素材处理；结束于全部约定文件通过视觉验收。首稿另记，包含预处理、生成、合成、排版、QA 与返工；用户等待单列，默认不事后扣除。20 分钟常规整套、5 分钟局部修改是待验证目标。

```bash
python3 scripts/production_guard.py benchmark \
  --manifest /project/run-01.json --manifest /project/run-02.json \
  --manifest /project/run-03.json --report /project/benchmark-01.json
```

每次有独立 run_id。所有已启动的有效任务进入分母，包括失败、超时和未完成；不得重复输入同一清单扩大样本。`first_round_qa_usable` 记录首轮全套 QA 是否可用；`rework_cycles` 记录返工次数，缺观测时相应比率为 `null`。`retry_request_rate` 是按槽位尝试计数的辅助指标，**不是**正式需求的“发生重试/返工任务数÷任务数”。正式看 `failed_retry_or_rework_run_rate`，且新建整套返工必须关联原任务，不能清零重试史。

同输入/同配置重做三次，用素材文件哈希+顺序、事实及模型/参数/分镜生成可追溯 `input_fingerprint/config_fingerprint`。工具只按提供的指纹分组，不证明相同输入。三次可用率**不等于**一致性；一致性需事前固定检查清单，按“三次均满足项÷预定项数”计算，硬性身份错误不得平均放行。

来自本次需求的验收目标：完整可用套图≤20分钟且达标率≥80%；局部修改≤5分钟；商品保真90–95%、Logo错误<2%、改色<3%；自然度≥75、贴图感≤2/5；平台通过95–100%、零乱码错字；核心卖点覆盖100%、A+完整≥90%；同输入三次一致性≥80%、返工/重试率<20%、首轮可用≥50%。**这些是尚待实测的目标，不是本次离线测试成绩。** 区间指标须在正式测试前确定单值、分母、样本量和证据来源；商品百分比需校准评审方法，平台通过率须真实平台审核，知识产权须可追溯素材权利；本地脚本不能担保这些结果。
