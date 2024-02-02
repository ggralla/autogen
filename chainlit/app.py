import sys
from typing import Dict, Optional, Union

from autogen import Agent, AssistantAgent, UserProxyAgent, config_list_from_json
import chainlit as cl
from autogen.agentchat.contrib.skilled_agent import SkilledAgent

# Chroma/SQLite compatibility hack
__import__("pysqlite3")
sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")


class ChainlitSkilledAgent(SkilledAgent):
    def send(
        self,
        message: Union[Dict, str],
        recipient: Agent,
        request_reply: Optional[bool] = None,
        silent: Optional[bool] = False,
    ) -> bool:
        cl.run_sync(
            cl.Message(
                content=f'*Sending message to "{recipient.name}":*\n\n{message}',
                author="SkilledAgent",
            ).send()
        )
        super(ChainlitSkilledAgent, self).send(
            message=message,
            recipient=recipient,
            request_reply=request_reply,
            silent=silent,
        )


class ChainlitUserProxyAgent(UserProxyAgent):
    def send(
        self,
        message: Union[Dict, str],
        recipient: Agent,
        request_reply: Optional[bool] = None,
        silent: Optional[bool] = False,
    ):
        cl.run_sync(
            cl.Message(
                content=f'*Sending message to "{recipient.name}"*:\n\n{message}',
                author="UserProxyAgent",
            ).send()
        )
        super(ChainlitUserProxyAgent, self).send(
            message=message,
            recipient=recipient,
            request_reply=request_reply,
            silent=silent,
        )


def config_agents():
    config_list = config_list_from_json(
        env_or_file="/workspaces/autogen/notebook/OAI_CONFIG_LIST",
        filter_dict={"model": ["gpt-3.5-turbo-1106", "github"]},
    )
    llm_config = {
        "config_list": config_list,
        "timeout": 60,
        "cache_seed": None,  # Use an int to seed the response cache. Use None to disable caching.
    }
    skilled_agent = ChainlitSkilledAgent(
        name="Skilled Agent",
        llm_config=llm_config,
        github_token=[config["api_key"] for config in config_list if config["model"] == "github"][0],
    )

    user_proxy = ChainlitUserProxyAgent(
        name="User Proxy",
        human_input_mode="NEVER",
        is_termination_msg=lambda x: True if "TERMINATE" in x.get("content") else False,
        max_consecutive_auto_reply=3,
    )

    return user_proxy, skilled_agent


def get_agents():
    return cl.user_session.get("user_proxy"), cl.user_session.get("skilled_agent")


@cl.on_message
async def on_message(message: cl.Message):
    user_proxy, skilled_agent = get_agents()
    # Get task from user input
    task = message.content
    await cl.Message(content=f"Starting agents on task: {task}...").send()
    await cl.make_async(user_proxy.initiate_chat)(
        skilled_agent,
        message=task,
    )

    # Run code once more to get the final output
    valid, final_message = user_proxy.generate_code_execution_reply(sender=skilled_agent)
    print("FINAL EXECUTION", final_message)
    if final_message:
        skilled_agent._append_oai_message(final_message, "user", user_proxy)
    if valid and "execution failed" in final_message:
        await cl.make_async(user_proxy.initiate_chat)(skilled_agent, message="Fix the error", clear_history=False)

    reflect_task = """Reflect on the sequence and refactor a into well-documented, generalized python function
    to perform similar tasks for coding steps in future. Make sure the function uses python type hints."""
    await cl.make_async(user_proxy.initiate_chat)(skilled_agent, message=reflect_task, clear_history=False)
    pull_request = skilled_agent.save_to_github()
    await cl.Message(content=f"Saved skill to Github, view Pull Request: {pull_request.html_url}").send()


@cl.on_chat_start
async def on_chat_start():
    user_proxy, skilled_agent = config_agents()
    cl.user_session.set("user_proxy", user_proxy)
    cl.user_session.set("skilled_agent", skilled_agent)
    await cl.Message(content="What is the task?").send()
