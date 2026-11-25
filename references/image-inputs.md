# v1.9 图片压缩、9 张参考图与请求体预检

## 边界与输入

这里保护的是本地客户端发往 SalpX 的请求，不是 Codex 的入站对话请求。客户端只读取本次 `--file` 指定的文件，不读取聊天历史、不自动添加生成结果。不要把一次本地检查通过说成上游已经完成 9 图实测。

图片操作 `single_image`/`fission` 允许 0–9 张，`background_replace` 允许 1–9 张，`outfit` 允许 2–9 张（人物、服装在前），`video` 仍只能传一张首帧。图片数量在文件解码/网络发送前检查；第 10 张导致明确报错，不会截断、拼图或自动拆成付费请求。

为每个参考编号并说明用途。避免混用多个 SKU；背景与细节参考不能覆盖原始商品身份。生成结果的数量与参考图数量独立：生成 6 张不需要上传 6 组参考图。

若 Codex 在执行 Skill 前就拒绝大消息，不能靠改客户端修复该条入站请求。让用户在新任务里提供本地文件路径；不要反复重发同一批大附件。可用本地预检生成较小副本供检查，但不要回显 Base64 或一次加载无关图片。

## 依赖与执行

脚本需要 Python 3.9+；图像预处理依赖 Pillow 10+。使用同一个 Python 环境安装和运行，优先使用已经有依赖的环境。缺少 Pillow 时在本地明确报错，不会退回原文件直接上传。

```bash
python3 -m pip install -r scripts/requirements.txt
python3 scripts/salpx_image_client.py --version
python3 scripts/salpx_image_client.py preflight --operation single_image --file product.png --file detail.png --prepared-dir ./project/.salpx-prepared
python3 scripts/salpx_image_client.py create --dry-run --operation single_image --file product.png --resolution 4k --ratio 4:5 --quality high --count 6
# Composition draft using the configured draft model profile:
python3 scripts/salpx_image_client.py create --dry-run --operation single_image --profile draft --file product.png
```

`preflight` 和 `create --dry-run` 都不需要 API Key、不调用网络，也不生成结果图。图片预检的 `model`、`size`、`quality` 和 `requests` 分别给出最终模型、请求尺寸、画质和计划请求次数；`submitted: false` 表示没有提交。`--prepared-dir` 是可选的；默认只在内存处理，需要检查副本时才写入指定目录下新的 `salpx-prepared-*` 子目录。不要在正常输出里展示 data URI、请求头或密钥。

## 默认阈值（MiB = 1,048,576 字节）

| 检查项 | 默认值与行为 |
| --- | --- |
| 参考数量 | 图片最多 9 张；第 10 张本地拦截 |
| 压缩后单张体积 | ≤2 MiB；可用 `--max-reference-mb` 调整，硬上限 5 MiB |
| 压缩后参考图总和 | ≤20 MiB；`--max-reference-total-mb` 可调低，不能高于 20 |
| 完整请求体 | ≤32 MiB；`--max-request-mb` 可调低，不能高于 32 |
| 参考图长边 | 初始上限 2560px；`--reference-max-edge` 可设 1280–4096 |
| 细节阈值 | JPEG 质量不低于 80；必要时等比缩小，长边不降到 1280px 以下；原本更小的图片保持原尺寸、不放大 |
| 单文件解码防护 | 原文件 ≤256 MiB，≤6400 万像素；超出要求先导出较小版本 |

以上是本地安全策略，不是 SalpX 或 Codex 的官方上限。即使总预算允许，默认 9 张每张 2 MiB 的图也不会超过 18 MiB。透明 PNG 或极高细节图片可能无法在预算与细节阈值之间同时合格，此时停止并说明具体文件，不牺牲透明通道或悄悄跳过图片。

## 处理顺序

1. 验证数量、操作、输出张数和预算；先检查提示词/JSON 本身是否已经超限。
2. 用实际文件内容识别格式，校正 EXIF 方向，读取 ICC；有色彩配置时转 sRGB。拒绝无法可靠转换的颜色模式/配置、无配置 CMYK、动图、多页文件、损坏图片或异常像素量。
3. 只生成参考副本，不修改原文件。保持比例、不裁切、不透视变形、不放大小图。去掉 EXIF 等元数据；有透明通道时保留为 PNG，无透明通道时编码为 JPEG，优先质量 95、90、85、80，然后才进一步缩小尺寸。
4. 按单张、总图像和完整请求预算分配可用字节。Base64 长度按 `4 × ceil(原始字节数 / 3)` 计算，另外包含 MIME 前缀、所有提示词、Unicode UTF-8 字节和 JSON 开销。
5. 用与真实发送完全相同的序列化函数再次检查完整请求；预检和传输都设置上限。任何失败都在生成请求前停止。
6. 输出安全预检报告：数量、原体积、压缩后体积、Base64 体积、完整请求体积、图像尺寸/格式及可选副本路径。不得输出编码后的图片内容。
7. 用户要求 6 张结果时，所有图片操作（包括 `fission`）均发送 6 次 `n=1` 的请求，只准备一次本次参考图，后续请求不附加上次结果。不同画面仍应有各自策划/提示词；输出数量本身不保证创意差异。

压缩会改变参考图像素，1280px/质量 80 只是停止阈值，不是细节保真保证。检查小字、缝线、纹理是否仍清晰；需要更清晰细节时减少参考图或使用明确的局部原图。**严格保真合成必须读取原始素材，不可用压缩副本替代原始商品像素。**

## 错误处理与验证

- 数量超限：列出数量，要求明确选择最多 9 张；不要自动付费拆单。
- 压缩失败：报告具体文件、预算和细节阈值；降低输入复杂度、减少参考，或在总上限内提高单图预算。
- 请求超限：缩短提示词/降低图像预算后重新本地预检；不得绕过检查直接发送。
- SalpX `413`：不重复发送原请求；按实际返回缩小 `--max-request-mb` 或减少参考。
- 上游拒绝 9 图：如实报告选定通道的限制，不称本地通过等于服务支持；先选图并征得新的付费拆单授权。
- Codex 入站超限：建议新任务＋本地路径；不宣称此脚本能清理历史请求。

离线回归（不会消耗 SalpX 额度）：

```bash
python3 -m unittest discover -s scripts -p 'test_image_preflight.py' -v
```

测试覆盖九张大图、第十张拦截、Base64/UTF-8 精确体积、原图不变、透明度/方向、异常文件、预算失败、重复输出不累加参考、缺依赖、目录创建和 CLI 不发网络请求。
