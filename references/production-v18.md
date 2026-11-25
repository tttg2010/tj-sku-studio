# v1.8 执行与验收

v1.8 在 v1.7 的套图、卖点证据、A/B、耗时和交付清单基础上增加一条硬规则：商品身份敏感的任务先锁定原始像素，SalpX 只生成场景底图，最终商品由本地合成。完整流程见 [original-pixel-compositing.md](original-pixel-compositing.md)。

## 1. 生产前冻结

在 manifest 中冻结：源图路径与 SHA256、商品身份和未知项、主图/附图/A+ 数量、每个槽位的目标尺寸、已证实卖点、参考图顺序、保真方法和输出路径。原图、cutout、场景底图和成图分开记录；`generated-*`、预检副本和旧输出不能回流到 source list。

每个槽位必须填写 `question`、`camera`、`composition`、`interaction`、`evidence_style`、`visual_proof`、`scene_fit` 和 `target_size`。附图/A+ 不能用主图缩放加文案充数；隐藏文案后仍需看见细节、机制、尺度、使用或包装证据。

## 2. 提交与合成

```bash
python3 scripts/production_guard.py plan --manifest /project/product/run.json
python3 scripts/production_guard.py next --manifest /project/product/run.json --slot main-01
```

对于 `original_pixels`：先运行 `matte_guard.py` 并人工查看多底色预览；再向 SalpX 提交无字场景底图请求；收到结果后使用原始 RGB 商品本地合成。请求记录只保留 request/task ID、状态、模型和时间，不保留密钥、请求头或 Base64。一次槽位最多初次提交加一次付费重试；`unknown/submitted` 未结算时只查询原任务。

## 3. 场景融合门

产品本体必须来自原始像素，且不做改变身份的透视拉伸、非等比缩放、改色、重绘或覆盖。仅允许在商品外部加入与场景一致的接触阴影、反射和局部遮挡。源图机位与场景不相容时换背景/机位或请求新的商品视图；不能用阴影掩盖悬浮、穿模、错误支撑和不可能受力。

## 4. 尺寸与交付门

```bash
python3 scripts/image_qa.py \
  --source /project/product/source.png \
  --output /project/product/generated-main-01.png \
  --report /project/product/qa/main-01.json
python3 scripts/production_guard.py delivery \
  --manifest /project/product/run.json \
  --report /project/product/qa/delivery.json
```

`delivery` 只有在每个实际文件可解码、尺寸精确匹配、没有重复输出、QA 报告对应当前文件 SHA256、具名视觉复核完整且所有约定槽位已交付时才能 `passed`。缺少视觉复核或独立蒙版证据为 `draft`；商品变形、改色、Logo/孔洞/细杆丢失、错误场景融合、尺寸错误或缺文件为 `blocked`。

页面级文字、箭头、尺寸、图标和对比标记应在底图验收后用确定性排版完成；不得把模型生成的文字框、卡片、标签或乱码当作 A+ 成品。重新排版后必须重新跑文件 QA 和输出哈希检查。

## 5. 复核记录

具名复核人按身份结构、原始材质、蒙版边缘、场景融合、卖点证据、文字排版、无虚构声明七项记录观察。复核记录必须绑定当前输出 SHA256；旧图被替换后，旧记录不能沿用。报告的 `passed` 只表示本地文件和已记录复核满足门禁，不表示平台已经审核，也不等于模型保证商品相似度。

