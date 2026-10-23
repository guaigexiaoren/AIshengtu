# 亦欣 AI 生图工作台

Windows 10/11 x64 桌面生图工具，使用 Nano Banana 三个型号生成和编辑图片。

## 当前功能

- Nano Banana 2.1、Nano Banana 2、Nano Banana Pro 切换
- 文字生图与 1–14 张参考图编辑，支持图片、文件夹和拖拽导入，并分别记忆上次目录
- 批量换装支持一对一、自由组合和自动匹配；可拖入文件/文件夹、裁剪恢复、拖动排序，并按窗口宽度自适应列数
- 首次升级内置基础服装替换和多图换装提示词，可在模板管理中编辑或删除
- 参考图和结果图统一编号预览，点击缩略图查看大图
- 参考图支持拖拽调整顺序、自由裁剪和恢复原图
- 参考图可拖拽调整顺序，并支持自由裁剪和恢复原图
- 单击创作页任务可恢复模型、提示词、参考图和全部生成参数
- 默认参考图编辑、`3:4`、`2K`，单次最多生成 4 张
- 串行后台队列、重启恢复、修改参数后重试和停止等待
- 队列和历史任务显示从提交到完成的总耗时
- 队列和历史显示从提交到完成的总耗时，执行中实时更新
- 历史记录、作品库、标签、搜索、提示词模板
- 作品库支持手动上传图片、递归导入文件夹和直接拖入文件或文件夹
- 作品详情显示实际保存路径，可一键打开所在文件夹
- 结果可分别保存到本地或作品库
- 创作页参考图与结果拖动分界线对比
- Windows DPAPI 加密 API Key、日志脱敏、7 天临时文件清理
- PyInstaller onedir 打包，数据固定保存在 EXE 同级 `data`
- 自定义深蓝星芒画笔图标，覆盖 EXE、窗口和任务栏

## 源码运行

```powershell
& 'C:\Users\YYMY\AppData\Local\Programs\Python\Python313\python.exe' main.py
```

首次启动后打开左下角“设置”，粘贴流光 API Key。软件只校验格式，不会主动调用验证密钥接口。

设置页还可以选择本地保存方式：

- 每次询问：每次保存选择文件夹，并记住上次目录
- 固定文件夹：直接保存到指定目录
- 参考图所在文件夹：使用任务最后一张参考图的来源目录

“保存到本地”只复制当前结果图；“保存到作品库”会同时保存结果、参考图、提示词和参数。
本地保存成功后使用右下角短提示，约 3 秒自动消失，不会阻塞后续操作。

## 自动化测试

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& 'C:\Users\YYMY\AppData\Local\Programs\Python\Python313\python.exe' -m unittest discover -s tests -v
```

测试使用模拟接口，不会发起真实付费生成。

## 打包

```powershell
& 'C:\Users\YYMY\AppData\Local\Programs\Python\Python313\python.exe' -m PyInstaller --noconfirm --clean 亦欣AI生图工作台.spec
```

输出目录：

```text
dist\亦欣AI生图工作台\亦欣AI生图工作台.exe
```

首次启动后会创建：

```text
data\config  加密配置
data\temp    临时结果
data\library 正式作品
data\logs    脱敏日志
data\app.db  历史、模板、标签和设置
```

每张作品保存在 `data\library\<作品文件夹>\`，其中包含：

```text
output.png 或原格式生成图
reference_01.png 等参考图
thumbnail.jpg 缩略图
```

升级时只替换 EXE 和 `_internal`，不要覆盖 `data`。

图标源文件位于 `assets/app_icon.svg`。修改后运行
`python tools/build_app_icon.py` 可重新生成 PNG、ICO 和尺寸预览。

## 真实接口验收

真实调用会产生费用。只有用户提供 API Key 并明确同意后，才使用 `n=1` 执行一次文字生图和一次参考图编辑。
