import os
from langchain_deepseek import ChatDeepSeek
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from src.state import WorkflowState
from src.prompts import CODER_SYSTEM_PROMPT
from pydantic import SecretStr

# 初始化 DeepSeek (请确保在跑代码前 .env 里有真实的 DEEPSEEK_API_KEY)
api_key_raw = os.environ.get("DEEPSEEK_API_KEY")
if not api_key_raw:
    raise ValueError("请设置 DEEPSEEK_API_KEY 环境变量")

api_key = SecretStr(api_key_raw)
llm = ChatDeepSeek(
    model="deepseek-chat", 
    api_key=api_key, 
    base_url="https://api.deepseek.com",
    temperature=0
)

def coder_node(state: WorkflowState):
    """
    负责将结构化 JSON 转化为 WDL 代码的节点
    """
    print("🤖 Coder 节点正在生成 WDL 代码...")
    
    # 1. 获取输入数据
    user_json = state.get("parsed_json", {})
    
    # 2. 组装 Prompt
    # 将 JSON 注入到提示词模板中
    system_prompt = CODER_SYSTEM_PROMPT.replace("{json_data}", str(user_json))
    
    # 3. 调用模型
    # 这里我们只传入 system_prompt，让模型专注于翻译代码
    messages = [SystemMessage(content=system_prompt)]
    response = llm.invoke(messages)
    
    # 4. 更新状态 (将生成的 WDL 存入 current_wdl，并把 AI 的回复追加到 messages)
    # 注意这里必须返回一个字典，LangGraph 会根据键名自动更新 State
    return {
        "current_wdl": response.content,
        "messages": [AIMessage(content="我已生成 WDL 代码。")]
    }