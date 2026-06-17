# extract_frames.py 使用说明

`scripts/extract_frames.py` 用于把本地视频按固定帧间隔或固定时间间隔抽取成图片文件。脚本依赖 `ffmpeg`，适合在导入视频素材前先生成可检查、可筛选的图片帧。

## 前置条件

1. 本机已安装 `ffmpeg`，并且命令在 `PATH` 中可用。
2. 在仓库根目录执行脚本，或使用脚本的完整路径执行。
3. 输入视频文件必须存在。

检查 `ffmpeg`：

```bash
ffmpeg -version
```

## 基本用法

```bash
python3 scripts/extract_frames.py <视频文件路径>
```

默认行为：

- 每 30 帧抽取 1 张图片
- 输出到 `output/` 目录
- 图片文件名格式为 `frame_000001.jpg`
- 输出格式为 `jpg`
- JPG 质量参数为 `-q:v 2`
- 不覆盖已有同名文件

## 参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `video` | 必填 | 输入视频文件路径 |
| `-i, --interval` | `30` | 每隔 N 个源视频帧抽取 1 张；仅在未设置 `--seconds` 时生效 |
| `-s, --seconds` | 无 | 每隔 N 秒抽取 1 张；设置后会覆盖 `--interval` 模式 |
| `-o, --output-dir` | `output` | 抽帧图片输出目录；不存在时会自动创建 |
| `--prefix` | `frame` | 输出文件名前缀，只保留字母、数字、下划线和连字符 |
| `--format` | `jpg` | 输出图片格式，可选 `jpg` 或 `png` |
| `--quality` | `2` | JPG 输出的 ffmpeg `-q:v` 质量参数，范围 `2` 到 `31`；数值越小质量越高 |
| `--overwrite` | 关闭 | 允许覆盖输出目录中已有的同名文件 |

## 示例

### 每 30 帧抽 1 张

```bash
python3 scripts/extract_frames.py ./videos/source.mp4
```

输出示例：

```text
output/frame_000001.jpg
output/frame_000002.jpg
output/frame_000003.jpg
```

### 每 10 帧抽 1 张

```bash
python3 scripts/extract_frames.py ./videos/source.mp4 --interval 10
```

### 每 2 秒抽 1 张

```bash
python3 scripts/extract_frames.py ./videos/source.mp4 --seconds 2
```

设置 `--seconds` 后，脚本会使用时间间隔模式，不再使用 `--interval`。

### 指定输出目录和文件名前缀

```bash
python3 scripts/extract_frames.py ./videos/source.mp4 \
  --output-dir ./output/source_frames \
  --prefix source
```

输出示例：

```text
output/source_frames/source_000001.jpg
output/source_frames/source_000002.jpg
```

### 输出 PNG

```bash
python3 scripts/extract_frames.py ./videos/source.mp4 \
  --format png \
  --output-dir ./output/source_png
```

`--quality` 只对 `jpg` 输出生效，输出 `png` 时不会传给 `ffmpeg`。

### 调整 JPG 质量

```bash
python3 scripts/extract_frames.py ./videos/source.mp4 \
  --quality 4 \
  --output-dir ./output/source_jpg_q4
```

`--quality` 可取 `2` 到 `31`。`2` 质量最高、文件更大；数值越大，文件通常越小，画质也会下降。

### 覆盖已有输出文件

```bash
python3 scripts/extract_frames.py ./videos/source.mp4 \
  --output-dir ./output/source_frames \
  --overwrite
```

未设置 `--overwrite` 时，如果目标文件已存在，`ffmpeg` 会拒绝覆盖并退出。

## 输出文件命名

输出文件使用以下格式：

```text
<output-dir>/<prefix>_%06d.<format>
```

例如：

```bash
python3 scripts/extract_frames.py ./videos/source.mp4 \
  --output-dir ./output/demo \
  --prefix sample \
  --format jpg
```

会生成类似：

```text
output/demo/sample_000001.jpg
output/demo/sample_000002.jpg
```

如果 `--prefix` 中包含空格或特殊字符，脚本会自动清理，只保留字母、数字、下划线和连字符。清理后为空时会回退为 `frame`。

## 常见错误

### `ffmpeg not found in PATH`

说明本机没有安装 `ffmpeg`，或安装后命令不在 `PATH` 中。安装并确认 `ffmpeg -version` 可正常执行后再运行脚本。

### `input video does not exist`

输入视频路径不存在，或传入的不是文件。请检查路径是否正确。

### `--seconds must be greater than 0`

`--seconds` 必须大于 `0`。

### `--interval must be at least 1`

未使用 `--seconds` 时，`--interval` 必须大于等于 `1`。

### `--quality must be between 2 and 31`

JPG 质量参数必须在 `2` 到 `31` 之间。

## 使用建议

- 需要尽量少的样本时，优先使用 `--seconds`，例如每 2 秒或每 5 秒抽 1 张。
- 需要按照原始视频帧稳定采样时，使用 `--interval`。
- 抽帧结果用于训练数据初筛时，建议先输出到独立目录，再人工删除模糊、重复或无目标的图片。
- 如果多次对同一个视频抽帧，建议为不同配置指定不同的 `--output-dir`，避免文件混在一起。
