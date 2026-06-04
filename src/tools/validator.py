import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_MISSING_MARKER = "未找到可用的 WDL 校验器"
MIN_WOMTOOL_JAVA_MAJOR = 17


@dataclass(frozen=True)
class ValidatorCommand:
    name: str
    label: str
    command: list[str]


def miniwdl_available() -> bool:
    executable = _miniwdl_executable()
    if executable is None:
        return False
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return False
    return result.returncode == 0


def womtool_available() -> bool:
    return _womtool_command() is not None


def wdl_validator_available() -> bool:
    return _selected_validator() is not None


@tool
def wdl_validator(wdl_code: str) -> dict:
    """
    使用 WOMtool（优先）或 miniwdl 校验 WDL 代码语法的合法性。
    如果代码有错，会返回具体的错误行号和原因。
    """
    logger.info("Validator tool is checking WDL syntax.")
    
    # 1. 创建一个安全的临时文件来存放 WDL 代码
    # delete=False 是因为 subprocess 需要在外部读取它，我们稍后手动删除
    with tempfile.NamedTemporaryFile(mode="w", suffix=".wdl", delete=False, encoding="utf-8") as temp_file:
        temp_file.write(wdl_code)
        temp_file_path = temp_file.name

    try:
        # 2. 使用子进程运行 WDL 校验器。Windows 下默认使用 Java/WOMtool。
        validator = _selected_validator()
        if validator is None:
            return _missing_validator_result()

        try:
            result = subprocess.run(
                [*validator.command, temp_file_path],
                capture_output=True,
                text=True,
                check=False,  # 设置为 False，这样报错时 Python 不会崩溃，而是让我们自己处理
                timeout=120,
            )
        except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
            return {
                "is_valid": False,
                "message": f"❌ WDL 校验器执行失败 ({validator.label})：{exc}",
            }

        # 3. 解析执行结果
        if result.returncode == 0:
            return {
                "is_valid": True,
                "message": f"✅ WDL 语法校验通过！{validator.label} 没有发现任何错误。"
            }
        else:
            # 提取报错信息（WDL 校验器的主要报错通常在 stderr 中）
            error_msg = result.stderr.strip() if result.stderr else result.stdout.strip()
            
            # 【高级工程技巧】
            # 将系统生成的长串临时路径（如 /tmp/tmp_abc123.wdl）替换为干净的文件名
            # 防止长串无意义的路径干扰大模型的注意力
            clean_error_msg = error_msg.replace(temp_file_path, "generated.wdl")
            
            return {
                "is_valid": False,
                "message": f"❌ WDL 语法校验失败！校验器：{validator.label}。请根据以下错误信息反思并重新输出修改后的完整代码：\n\n{clean_error_msg}"
            }

    finally:
        # 4. 无论成功还是失败，都必须清理系统垃圾（删除临时文件）
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


def _selected_validator() -> ValidatorCommand | None:
    requested = os.environ.get("WDL_VALIDATOR", "auto").strip().lower()
    if requested in {"womtool", "wom"}:
        return _womtool_command()
    if requested == "miniwdl":
        return _miniwdl_command()
    if requested not in {"", "auto"}:
        logger.warning("Unknown WDL_VALIDATOR=%s; falling back to auto.", requested)

    return _womtool_command() or _miniwdl_command()


def _womtool_command() -> ValidatorCommand | None:
    jar_path = _womtool_jar()
    if jar_path is None:
        return None

    for java_executable in _java_candidates():
        major = _java_major_version(java_executable)
        if major is not None and major < MIN_WOMTOOL_JAVA_MAJOR:
            logger.warning(
                "Ignoring Java %s for WOMtool; Java %s+ is required.",
                java_executable,
                MIN_WOMTOOL_JAVA_MAJOR,
            )
            continue

        return ValidatorCommand(
            name="womtool",
            label=f"WOMtool ({jar_path.name})",
            command=[str(java_executable), "-jar", str(jar_path), "validate"],
        )

    return None


def _womtool_jar() -> Path | None:
    configured = os.environ.get("WOMTOOL_JAR")
    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.exists():
            return configured_path
        logger.warning("WOMTOOL_JAR points to a missing file: %s", configured_path)

    cache_dir = PROJECT_ROOT / ".cache" / "womtool"
    preferred = cache_dir / "womtool.jar"
    if preferred.exists():
        return preferred

    jars = sorted(cache_dir.glob("womtool-*.jar"), key=lambda path: path.stat().st_mtime, reverse=True)
    return jars[0] if jars else None


def _java_executable() -> Path | None:
    for candidate in _java_candidates():
        return candidate
    return None


def _java_candidates() -> list[Path]:
    java_name = "java.exe" if os.name == "nt" else "java"
    candidates: list[Path] = []

    java_exe = os.environ.get("JAVA_EXE")
    if java_exe:
        java_path = Path(java_exe).expanduser()
        if java_path.exists():
            candidates.append(java_path)

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        java_path = Path(java_home).expanduser() / "bin" / java_name
        if java_path.exists():
            candidates.append(java_path)

    local_cache = PROJECT_ROOT / ".cache" / "java"
    local_candidates = [candidate for candidate in local_cache.glob(f"**/bin/{java_name}") if candidate.exists()]
    if os.name != "nt":
        local_candidates.extend(
            candidate for candidate in local_cache.glob("**/bin/java.exe") if candidate.exists()
        )
    local_candidates.sort(key=lambda candidate: _java_major_version(candidate) or 0, reverse=True)
    candidates.extend(local_candidates)

    path_java = shutil.which("java")
    if path_java:
        candidates.append(Path(path_java))

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            deduped.append(candidate)
            seen.add(resolved)

    return deduped


def _java_major_version(java_executable: Path) -> int | None:
    try:
        result = subprocess.run(
            [str(java_executable), "-version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None

    version_output = result.stderr or result.stdout
    match = re.search(r'version "(?P<version>[^"]+)"', version_output)
    if not match:
        return None

    version = match.group("version")
    if version.startswith("1."):
        parts = version.split(".")
        return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None

    major = version.split(".", 1)[0]
    return int(major) if major.isdigit() else None


def _miniwdl_command() -> ValidatorCommand | None:
    executable = _miniwdl_executable()
    if executable is None or not miniwdl_available():
        return None
    return ValidatorCommand(
        name="miniwdl",
        label="miniwdl",
        command=[executable, "check"],
    )


def _miniwdl_executable() -> str | None:
    executable = shutil.which("miniwdl")
    if executable:
        return executable

    sibling = Path(sys.executable).with_name("miniwdl")
    if sibling.exists():
        return str(sibling)

    return None


def _missing_validator_result() -> dict:
    return {
        "is_valid": False,
        "message": (
            f"❌ {VALIDATOR_MISSING_MARKER}。请运行 `scripts/install_java.ps1` 和 "
            "`scripts/install_womtool.ps1` 下载 Java 17+ 与 WOMtool，或设置 "
            "`JAVA_HOME` / `JAVA_EXE` / `WOMTOOL_JAR` 指向本地工具。"
        ),
    }
