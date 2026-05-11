import os
from dotenv import load_dotenv

# 确保在导入任何核心逻辑前加载环境变量
load_dotenv()

# 检查 API Key 是否存在
if not os.environ.get("DEEPSEEK_API_KEY"):
    raise ValueError("未找到 DEEPSEEK_API_KEY，请检查 .env 文件是否配置正确！")

# 导入我们编译好的总 Agent
from src.graph import agent

def main():
    print("🚀 启动 AI-bioworkflow MVP 测试...\n")
    
    # 模拟用户在前端界面填写的结构化表单
    mock_user_input = {
        "workflow_name": "SimpleQC",
        "inputs": {
            "raw_fastq": "File"
        },
        "tasks": [
            {
                "name": "fastp_qc",
                "docker": "quay.io/biocontainers/fastp:0.23.2",
                "command": "fastp -i ~{raw_fastq} -o out.fq",
                "outputs": {
                    "clean_fastq": "File"
                }
            }
        ]
    }
    
    # 初始化状态笔记本
    initial_state = {
        "parsed_json": mock_user_input,
        "messages": [],
        "current_wdl": "",
        "error_count": 0
    }
    
    # 启动 Agent！
    print("⏳ 正在请求 DeepSeek 生成代码，请稍候...")
    final_state = agent.invoke(initial_state)
    
    # 打印最终结果
    print("\n" + "="*50)
    print("🎉 WDL 生成成功！以下是代码：\n")
    print(final_state["current_wdl"])
    print("="*50)

if __name__ == "__main__":
    main()