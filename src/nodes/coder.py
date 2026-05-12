import os
import json
from langchain_deepseek import ChatDeepSeek
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from src.state import WorkflowState
from src.prompts import coder_prompt
from pydantic import SecretStr

# 初始化 DeepSeek (请确保在跑代码前 .env 里有真实的 DEEPSEEK_API_KEY)
api_key_raw = os.environ.get("DEEPSEEK_API_KEY")
if not api_key_raw:
    raise ValueError("请设置 DEEPSEEK_API_KEY 环境变量")

api_key = SecretStr(api_key_raw)
llm = ChatDeepSeek(
    model="deepseek-v4-pro", 
    api_key=api_key, 
    base_url="https://api.deepseek.com",
    temperature=0
)

def coder_node(state: WorkflowState):
    print("🤖 Coder 节点正在生成 WDL 代码...")
    
    # 1. 获取输入数据
    user_json = state.get("parsed_json", {})
    
    # 小技巧：将 Python 字典转为带缩进的 JSON 字符串，大模型阅读起来准确率更高
    formatted_json = json.dumps(user_json, indent=2, ensure_ascii=False)

    # 2. 组装 Prompt (利用 LangChain 的 invoke 自动填充变量并生成 Message 列表)
    messages = coder_prompt.invoke({"json_data": formatted_json})
    
    # 3. 调用模型
    response = llm.invoke(messages)
    
    # 4. 更新状态
    return {
        "current_wdl": response.content,
        "messages": [AIMessage(content="我已生成 WDL 代码。")]
    }