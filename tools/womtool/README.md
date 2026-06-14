# WOMtool

本目录记录项目本地 WOMtool 的安装约定。不要把 WOMtool JAR 提交到仓库中。

从仓库根目录运行安装脚本：

```powershell
scripts/install_womtool.ps1
```

默认情况下，脚本会从 Broad Institute Cromwell GitHub Releases 下载 `womtool-91.jar`，并保存到：

```text
.cache/womtool/womtool.jar
```

项目的 `WDL validator` 会自动从该 cache 路径发现 JAR。也可以通过环境变量覆盖：

```env
WOMTOOL_JAR="D:/path/to/womtool.jar"
```

默认 WOMtool 91 release 需要 Java 17 或更新版本。如需安装项目本地的 Temurin JDK：

```powershell
scripts/install_java.ps1
```
