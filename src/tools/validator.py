import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from langchain_core.tools import tool


def miniwdl_available() -> bool:
    return _miniwdl_executable() is not None


@tool
def wdl_validator(wdl_code: str) -> dict:
    """
    使用 miniwdl 校验 WDL 代码语法的合法性。
    如果代码有错，会返回具体的错误行号和原因。
    """
    print("🛠️ Validator 工具正在校验代码语法...")
    
    # 1. 创建一个安全的临时文件来存放 WDL 代码
    # delete=False 是因为 subprocess 需要在外部读取它，我们稍后手动删除
    with tempfile.NamedTemporaryFile(mode='w', suffix='.wdl', delete=False) as temp_file:
        temp_file.write(wdl_code)
        temp_file_path = temp_file.name

    try:
        # 2. 使用子进程在命令行中运行 `miniwdl check`
        miniwdl_executable = _miniwdl_executable()
        if miniwdl_executable is None:
            return _missing_miniwdl_result()

        try:
            result = subprocess.run(
                [miniwdl_executable, "check", temp_file_path],
                capture_output=True,
                text=True,
                check=False  # 设置为 False，这样报错时 Python 不会崩溃，而是让我们自己处理
            )
        except FileNotFoundError:
            return _missing_miniwdl_result()

        # 3. 解析执行结果
        if result.returncode == 0:
            return {
                "is_valid": True,
                "message": "✅ WDL 语法校验通过！没有发现任何错误。"
            }
        else:
            # 提取报错信息（miniwdl 的主要报错通常在 stderr 中）
            error_msg = result.stderr.strip() if result.stderr else result.stdout.strip()
            
            # 【高级工程技巧】
            # 将系统生成的长串临时路径（如 /tmp/tmp_abc123.wdl）替换为干净的文件名
            # 防止长串无意义的路径干扰大模型的注意力
            clean_error_msg = error_msg.replace(temp_file_path, "generated.wdl")
            
            return {
                "is_valid": False,
                "message": f"❌ WDL 语法校验失败！请根据以下错误信息反思并重新输出修改后的完整代码：\n\n{clean_error_msg}"
            }

    finally:
        # 4. 无论成功还是失败，都必须清理系统垃圾（删除临时文件）
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


def _miniwdl_executable() -> str | None:
    executable = shutil.which("miniwdl")
    if executable:
        return executable

    sibling = Path(sys.executable).with_name("miniwdl")
    if sibling.exists():
        return str(sibling)

    return None


def _missing_miniwdl_result() -> dict:
    return {
        "is_valid": False,
        "message": "❌ 未找到 miniwdl 可执行文件，请先安装依赖或使用 `uv run` 执行。"
    }
