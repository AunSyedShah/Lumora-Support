from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.tools.email import EmailTools

agent = Agent(
    model=DeepSeek(id="deepseek-v4-flash", api_key="from env"),
    tools=[EmailTools()]
)