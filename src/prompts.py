from langchain_core.prompts import (ChatPromptTemplate, PromptTemplate,
                                    SystemMessagePromptTemplate)

_CODER_SYSTEM_TEMPLATE = """
你是一个世界顶级的生物信息学工程师，精通 WDL (Workflow Description Language) 1.0 规范。
你的任务是将用户提供的结构化 JSON 步骤说明，翻译成标准的、无语法错误的 WDL 代码。

【约束条件】
1. 必须包含一个 workflow {} 块和所有必需的 task {} 块。
2. 变量传递必须严格使用 ~{variable} 语法。
3. 每个 task 必须包含 command <<< >>>、runtime 和 output 块。
4. 你只需要输出 WDL 代码，不需要提供任何 markdown 格式或解释性的废话。直接输出纯文本代码。

【用户的 JSON 描述如下】：
{{ json_data }}
"""

# 明确指定 template_format="jinja2"
jinja2_prompt = PromptTemplate(
    template=_CODER_SYSTEM_TEMPLATE,
    template_format="jinja2",
    input_variables=["json_data"]
)

# 暴露出最终的 ChatPromptTemplate
coder_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate(prompt=jinja2_prompt)
])