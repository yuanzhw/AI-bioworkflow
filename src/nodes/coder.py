import json
import logging
import os
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_deepseek import ChatDeepSeek
from pydantic import SecretStr

from src.prompts import coder_prompt
from src.state import WorkflowState


logger = logging.getLogger(__name__)

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
    logger.info("Coder node is generating WDL code.")
    
    # 1. 获取输入数据
    user_json = state.get("parsed_json", {})
    
    # 小技巧：将 Python 字典转为带缩进的 JSON 字符串，大模型阅读起来准确率更高
    formatted_json = json.dumps(user_json, indent=2, ensure_ascii=False)

    # 2. 组装基础的 System Prompt (返回的是 PromptValue 对象)
    prompt_value = coder_prompt.invoke({"json_data": formatted_json})
    
    # 3. 转换成标准的 Message 列表
    base_messages = prompt_value.to_messages()
    
    # 4. 获取历史记录（包含之前的错误代码和 Checker 的打回报错）
    history_messages = state.get("messages", [])
    
    # 5. 完美拼接：系统设定在前，历史记录在后
    final_messages = base_messages + history_messages
    
    # 6. 调用模型
    response = llm.invoke(final_messages)
    raw_content = str(response.content)

    # 【新增功能】：剥离 Markdown 代码块标记，提取纯 WDL 代码
    clean_wdl = raw_content
    match = re.search(r"```(?:wdl)?\s*(.*?)\s*```", raw_content, re.DOTALL | re.IGNORECASE)
    if match:
        clean_wdl = match.group(1).strip()
    
    # 7. 更新状态
    return {
        "current_wdl": clean_wdl,
        "messages": [AIMessage(content="我已生成 WDL 代码。")]
    }
