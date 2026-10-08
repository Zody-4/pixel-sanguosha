# 开发说明

Python 3.12 建立虚拟环境，安装 requirements.txt。模型与制作环境不是游戏运行依赖。运行界面需要完整资源。

## 自动测试

以下命令隔离用户设置、战绩和诊断数据：

```powershell
@'
import os, subprocess, sys, tempfile
with tempfile.TemporaryDirectory(prefix="xssgkpz-tests-") as data:
    env = os.environ.copy()
    env["LOCALAPPDATA"] = data
    env["SDL_VIDEODRIVER"] = "dummy"
    env["SDL_AUDIODRIVER"] = "dummy"
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], env=env)
    sys.exit(result.returncode)
'@ | .\.venv\Scripts\python.exe -
```

部分启动／呈现场景依赖完整美术资源，默认仅已核实素材导出不能保证全套通过。本次完整发行包含资源与测试依赖的追踪矩阵。2026-10-08用户授权运行测试，243项通过；AI协作代理仍只在用户要求时运行测试。

## 贡献

描述触发条件、预期与实际行为、验证范围。保持既有25将／108牌和模式规则，玩法变更先讨论。新增素材附作者、原链接、许可及修改方式。不提交环境、日志、存档、密钥、下载参考资料或许可未知的截图。
