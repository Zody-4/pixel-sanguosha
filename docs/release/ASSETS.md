# 素材来源与公开范围

2026-10-08。作者进一步说明：25张人物、锦囊、小配件及其他图像为AI原创；杀的插图形象参考、身份卡、武器装备非原创。两项外部音效保留并标来源、提供侵权删除联系渠道。逐文件路径、SHA256、来源依据及分发状态见 runtime-assets.json。
redistributable表示已登记许可／作者来源确认并核对哈希；pending表示素材权限未核实。默认导出排除pending，本次完整发行按用户要求通过include-unverified-assets保留并附来源说明；这不将pending改成授权通过。用户进一步说明非原创图片均为老版经典卡牌形象，具体原图链接和原权利人仍未核实。

| 内容 | 找到的证据 | 当前处理 |
|---|---|---|
| 25张人物、锦囊、其他基本牌、配件及UI | 作者2026-10-08确认AI原创；清单按类别映射 | 在作者有权授权范围内按CC-BY-4.0纳入公开包，见ASSET_LICENSE.md |
| 独立文字／花色／点数层 | 项目分层渲染，不含对应外部插画 | 按CC-BY-4.0提供；不放行含第三方插画的完整底图 |
| 杀的底图、4张身份卡、装备底图 | 用户说明来自老版经典卡牌形象，具体取得链接／许可未齐 | 按用户发行要求保留并说明来源，许可仍pending |
| 主菜单／对局 BGM | v19 menu、v30 A，Stable Audio 3 Small-Music，source_audio=null | 不把较早 ACE-Step 草稿当成最终来源；输出条款待核实 |
| 报牌／轮到你了 | Qwen3-TTS Base／VoiceDesign，v03→v04及后续补充 | 不误称官方录音；参考音色和输出条件待核实 |
| 治疗／伤害 | 无名杀recover.mp3／damage.mp3直接转WAV，asset_license_verified=false | 按用户要求保留，附来源与“如有侵权联系删除”；许可仍未核实，见ASSET_CREDITS.md |
| 操作／胜负等8项音效 | Kenney CC0，最终哈希匹配v37／v38／v40／v41产物，生产记录中原音哈希全部匹配，三份原许可保留 | 以CC0-1.0纳入公开包；本项目对这些音效的编辑贡献同样按CC0提供 |
| 中文备用字体 | 固定上游版本、哈希、OFL 文本 | 字体、许可、sources.json 一起进入公开包 |

来源：[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)、[Stable Audio 3 Small Music](https://huggingface.co/stabilityai/stable-audio-3-small-music/blob/main/README.md)、[Kenney](https://kenney.nl/assets)、[霞鹜文楷](https://github.com/lxgw/LxgwWenKai)、[Noto CJK](https://github.com/notofonts/noto-cjk)。
本说明记录证据边界，不承诺 AI 输出不存在相似性或第三方权利问题。截图可能包含未核实素材，暂不放入公开 README。

补授权时记录作者、原链接、许可全文／明确授权、修改方式、文件哈希及署名要求。没有权限的素材取得授权或换成来源明确的独立作品；不能仅改清单状态就算取得授权。
