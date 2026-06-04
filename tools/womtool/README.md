# WOMtool

This directory documents the local WOMtool setup. Do not commit the WOMtool
JAR into the repository.

Use the installer script from the repository root:

```powershell
scripts/install_womtool.ps1
```

By default it downloads `womtool-91.jar` from the Broad Institute Cromwell
GitHub releases and stores it under:

```text
.cache/womtool/womtool.jar
```

The validator discovers the JAR automatically from that cache path. You can
override it with:

```env
WOMTOOL_JAR="D:/path/to/womtool.jar"
```

The default WOMtool 91 release needs Java 17 or newer. For a project-local
Temurin JDK:

```powershell
scripts/install_java.ps1
```
