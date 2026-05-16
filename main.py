from dotenv import load_dotenv

from src.state import WorkflowState

# 仍然加载 .env，后续如果接入 LLM planner / repairer 可以直接复用
load_dotenv()

# 导入我们编译好的总 Agent
from src.graph import agent


def main():
    print("🚀 启动 AI-bioworkflow MVP 测试...\n")
    
    # 模拟用户在前端界面填写或由 LLM planner 产出的标准 Workflow IR
    mock_user_input = {
        "workflow": {
            "name": "RNASeqPipeline",
            "inputs": {
                "raw_r1": "File",
                "raw_r2": "File",
                "reference": "File"
            },
            "calls": [
                {
                    "id": "qc",
                    "task": "fastp",
                    "inputs": {
                        "r1": "raw_r1",
                        "r2": "raw_r2"
                    }
                },
                {
                    "id": "align",
                    "task": "bwa_mem",
                    "inputs": {
                        "r1": "qc.clean_r1",
                        "r2": "qc.clean_r2",
                        "ref": "reference"
                    }
                }
            ],
            "outputs": {
                "bam": "align.bam"
            }
        },
        "tasks": {
            "fastp": {
                "inputs": {
                    "r1": "File",
                    "r2": "File"
                },
                "command": "fastp -i ~{r1} -I ~{r2} -o clean_R1.fq.gz -O clean_R2.fq.gz",
                "outputs": {
                    "clean_r1": {
                        "type": "File",
                        "value": "\"clean_R1.fq.gz\""
                    },
                    "clean_r2": {
                        "type": "File",
                        "value": "\"clean_R2.fq.gz\""
                    }
                },
                "runtime": {
                    "docker": "quay.io/biocontainers/fastp:0.23.2",
                    "cpu": 4,
                    "memory": "8G"
                }
            },
            "bwa_mem": {
                "inputs": {
                    "r1": "File",
                    "r2": "File",
                    "ref": "File"
                },
                "command": "bwa mem ~{ref} ~{r1} ~{r2} > aligned.sam",
                "outputs": {
                    "bam": {
                        "type": "File",
                        "value": "\"aligned.sam\""
                    }
                },
                "runtime": {
                    "docker": "quay.io/biocontainers/bwa:0.7.17--hed695b0_7",
                    "cpu": 8,
                    "memory": "32G"
                }
            }
        }
    }
    
    # 初始化状态笔记本
    initial_state: WorkflowState = {
        "parsed_json": mock_user_input,
        "workflow_ir": {},
        "analysis_errors": [],
        "analysis_warnings": [],
        "messages": [],
        "current_wdl": "",
        "validation_message": "",
        "error_count": 0,
        "repair_count": 0,
        "repair_actions": [],
        "is_valid": False
    }
    
    # 启动 Agent！
    print("⏳ 正在标准化 IR、渲染 WDL 并运行 miniwdl 校验...")
    final_state = agent.invoke(initial_state)
    
    # 打印最终结果
    print("\n" + "="*50)
    print("🎉 WDL 生成完成！以下是代码：\n")
    print(final_state["current_wdl"])
    print("="*50)

if __name__ == "__main__":
    main()
