# Windows发行与诊断补丁

程序0.1.0，规则early-standard-25-108-v1。本次发行仅面向Windows桌面。

## 下载与运行

在[Releases](https://github.com/Zody-4/pixel-sanguosha/releases)下载完整Windows ZIP，完整解压后运行xssgkpz.exe，保留旁边的_internal目录。无需安装Python。
SHA256SUMS.txt提供压缩包校验值。程序没有代码签名，不宣称已通过系统信誉验证；保留系统安全防护。

## 诊断补丁

新完整包已经包含本地PC诊断功能，不需要旧补丁。旧诊断补丁用于此前私下交付版本，只增加记录，不代表白屏原因已经修复。
未来exe-only补丁必须记录基线exe哈希、核对_internal全部文件与标准库成员内容一致；运行库改变则提供完整包。
本次不发布旧补丁作为通用更新，避免旧版联系方式和基线不匹配问题。

诊断目录为`%LOCALAPPDATA%\xssgkpz\diagnostics`，仅本地保存，不自动上传。通过[Issues](https://github.com/Zody-4/pixel-sanguosha/issues)反馈问题，分享日志前删去个人信息。

## 从源码重建

```powershell
py -3.12 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv-build\Scripts\python.exe tools/build_public_windows.py --output dist/windows-release --include-unverified-assets
```

输出目录必须不存在，不覆盖旧交付。工具核对资源哈希、收集实际环境随附许可、生成目录式程序、ZIP和校验值，不自动运行游戏。
默认模式要求全部资源权限登记通过；本次按用户选择保留经典卡牌与两项外部录音，显式include-unverified-assets导出并保留pending及来源说明。此选择不等于取得原权利人的授权，代码MIT不覆盖全部素材。
源码和素材来自新的明确清单快照，不复制原私有Git历史或内部制作资料。

## 验证边界

2026-10-08已完成243项自动测试及源码／exe单帧启动，详见VERIFICATION.md。未完成本次长时真人游玩、声音试听、另一台电脑兼容性或白屏复现验证。
素材分类、来源、许可边界与权利联系见ASSETS.md、ASSET_LICENSE.md、ASSET_CREDITS.md及NOTICE.md。
