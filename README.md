<div align="center">

[![使用 SalpX 开始 AI 电商批量修图](assets/salpx-register-banner.jpg)](https://www.salpx.com/?lang=zh)

# TJ SKU Studio

**TJ 电商批量修图 · 从商品原图到可交付电商图的 AI 生产工作流**

[注册 SalpX](https://www.salpx.com/?lang=zh) · [查看 API 文档](https://www.salpx.com/api-docs/) · [阅读 Skill](SKILL.md)

</div>

## 项目简介

TJ SKU Studio 是一个面向电商商品图生产的开放 Skill。它把创意规划、参考图预检、SalpX 图像生成、原始像素合成和交付质检串成可复用流程，适合在 WorkBuddy、Codex 等支持 Skill 的智能体环境中使用，也可以直接调用仓库内脚本。

默认通过 SalpX 的 OpenAI 兼容接口使用 `gpt-image-2.6-sunburst`：

- 默认分辨率：**2K**
- 默认图片质量：**max**
- 可选分辨率：**2K / 4K**
- 可选质量：`low` / `medium` / `high` / `max`
- 支持比例：`1:1`、`4:5`、`3:4`、`16:9`、`9:16` 等
- 选择 4K 时自动切换到 `gpt-image-2.6-sunburst-4k`

> README 横幅的视觉和图文均由本 Skill 通过 SalpX `gpt-image-2.6-sunburst-4k` 直接生成。

## 核心能力

### 1. 电商图片生成与编辑

- 单图生成、换背景、穿搭/换装和多图裂变
- 根据市场、平台、受众和卖点规划图片结构
- 支持商品主体图、细节图、功能图、场景图和生活方式图
- 多张参考图自动预检、压缩和请求体积控制

### 2. 原始像素保护

对包装文字、Logo、条码、标签和关键结构要求严格的场景，可使用“生成场景底图 + 本地原始像素合成”路线，避免让生成模型重画关键商品区域。

### 3. 生产质检

内置脚本检查：

- 分辨率、尺寸比例和文件格式
- Alpha 通道、主体边缘和白底/透明底质量
- 输出命名、manifest 和生产交付状态
- Amazon 等平台的常见主图规则

## 快速开始

### 方式一：安装为 Skill

把本仓库放入智能体支持的 Skill 目录，并让智能体读取 `SKILL.md`。完整工作流、参考资料、模板和脚本都包含在仓库内。

```bash
git clone https://github.com/tttg2010/tj-sku-studio.git
```

### 方式二：直接运行脚本

安装轻量依赖：

```bash
python3 -m pip install -r scripts/requirements.txt
```

注册 [SalpX](https://www.salpx.com/?lang=zh)，创建 API Key，然后复制配置模板：

```bash
cp references/salpx.env.example .env
```

在本机 `.env` 填写：

```dotenv
SALPX_API_KEY=填写你自己的_key
SALPX_BASE_URL=https://www.salpx.com/v1
SALPX_IMAGE_MODEL=gpt-image-2.6-sunburst
```

`.env` 已被 `.gitignore` 排除。**不要把真实 Key 写进聊天、截图、日志或 Git 提交。**

## 使用示例

### 默认：2K + max + 1:1

```bash
python3 scripts/salpx_image_client.py create \
  --operation single_image \
  --prompt "高端护肤品白底电商主图，真实材质，柔和棚拍光"
```

### 4K + max + 16:9

```bash
python3 scripts/salpx_image_client.py create \
  --operation single_image \
  --ratio 16:9 \
  --resolution 4k \
  --quality max \
  --prompt "现代科技感电商横幅，突出商品与使用场景"
```

### 4K + low + 4:5

分辨率和图片质量可独立组合：

```bash
python3 scripts/salpx_image_client.py create \
  --operation single_image \
  --ratio 4:5 \
  --resolution 4k \
  --quality low \
  --prompt "社交电商商品海报，留出标题空间"
```

### 只做本地预检，不提交生成

```bash
python3 scripts/salpx_image_client.py preflight \
  --operation single_image \
  --ratio 4:5 \
  --resolution 4k \
  --quality low
```

## 目录结构

```text
.
├── SKILL.md                 # Skill 入口与完整流程
├── agents/                  # Agent 配置
├── assets/                  # README 视觉资产
├── references/              # API、创意规划、平台规范与生产说明
├── scripts/                 # SalpX 客户端、预检、合成与质检脚本
└── templates/               # 生产 manifest 模板
```

## 安全说明

- 仓库不包含任何真实 API Key、个人凭据或私有配置。
- 真实 Key 仅保存在环境变量、本机 `.env` 或用户配置目录。
- 客户端不会在正常结果中回显授权头。
- 提交公开 Issue 或日志前，请再次检查并遮盖 Key、订单、客户和商品隐私信息。

## 测试

```bash
python3 -m unittest discover -s scripts -q
```

当前版本：**v1.9**。

## 许可证

本项目暂未声明开源许可证。未经明确许可，不代表允许复制、再分发或商用；后续可按维护者决定补充许可证。
