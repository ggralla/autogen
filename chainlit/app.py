import sys
from typing import Dict, Optional, Union

from autogen import Agent, AssistantAgent, UserProxyAgent, config_list_from_json
import chainlit as cl

from autogen.agentchat.discovery_agent import DiscoveryAgent

# Chroma/SQLite compatibility hack
__import__("pysqlite3")
sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
from autogen.agentchat.contrib.skilled_agent import SkilledAgent  # noqa: E402


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


def patched_send(
    self,
    message: Union[Dict, str],
    recipient: Agent,
    request_reply: Optional[bool] = None,
    silent: Optional[bool] = False,
):
    cl.run_sync(
        cl.Message(
            content=f'*Sending message to "{recipient.name}"*:\n\n{message}',
            author="Discovery Agent",
        ).send()
    )
    super(self.__class__, self).send(
        message=message,
        recipient=recipient,
        request_reply=request_reply,
        silent=silent,
    )


def init_agents():
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
        name="Code Execution User Proxy",
        human_input_mode="NEVER",
        is_termination_msg=lambda x: True if "TERMINATE" in x.get("content") else False,
        max_consecutive_auto_reply=3,
    )

    discovery_user_proxy = ChainlitUserProxyAgent(
        name="Skill Planning User Proxy",
        human_input_mode="NEVER",
        max_consecutive_auto_reply=0,
    )

    DiscoveryAgent.send = patched_send
    discovery_agent = DiscoveryAgent(
        name="DiscoveryAgent",
        llm_config=llm_config,
    )
    cl.user_session.set("user_proxy", user_proxy)
    cl.user_session.set("skilled_agent", skilled_agent)
    cl.user_session.set("discovery_user_proxy", discovery_user_proxy)
    cl.user_session.set("discovery_agent", discovery_agent)


def get_agents():
    return cl.user_session.get("user_proxy"), cl.user_session.get("skilled_agent")


@cl.on_message
async def on_message(message: cl.Message):
    user_proxy, skilled_agent = get_agents()
    # Get task from user input
    task = message.content
    await cl.Message(content=f"Starting agents on task: {task}...").send()
    async with cl.Step(name="Initial Implementation") as step:
        await cl.make_async(user_proxy.initiate_chat)(
            skilled_agent,
            message=task,
        )
        step.set_output("task", task)


@cl.on_chat_start
async def on_chat_start():
    init_agents()
    await cl.Message(content="What is the task?").send()

    files = None

    # Wait for the user to upload a file
    while files is None:
        files = await cl.AskFileMessage(
            content="Please upload a data file to begin brainstorming and analysis",
            accept=["any"],
        ).send()

    text_file = files[0]

    discovery_agent = cl.user_session.get("discovery_agent")
    discovery_user_proxy = cl.user_session.get("discovery_user_proxy")
    user_proxy = cl.user_session.get("user_proxy")
    skilled_agent = cl.user_session.get("skilled_agent")

    discovery_agent.load_data(text_file.path)

    # Let the user know that the system is ready
    await cl.Message(content=f"`{text_file.name}` uploaded, it contains {discovery_agent.describe_data()}").send()

    discovery_message = f"what are some useful basic python functions that could be written to analyze a datase with the following structure and sample data: {discovery_agent.describe_data()}?"
    await cl.make_async(discovery_user_proxy.initiate_chat)(discovery_agent, message=discovery_message)
    for idea in discovery_agent.generated_ideas:
        success = await generate_skill_code(user_proxy, skilled_agent, discovery_agent, idea)
        if not success:
            print("FAILED TO GENERATE CODE FOR IDEA: ", idea)


async def generate_skill_code(user_proxy, skilled_agent, discovery_agent, task):
    skill_prompt = f"""Write python code to {task}. Make sure it uses the dataset provided, with the filename "/workspaces/autogen/notebook/data/data.csv". The dataset has the following structure and sample data: {discovery_agent.describe_data()}"""
    await cl.make_async(user_proxy.initiate_chat)(
        skilled_agent,
        message=skill_prompt,
    )
    # Run code once more to get the final output
    valid, final_message = user_proxy.generate_code_execution_reply(sender=skilled_agent)
    print("FINAL EXECUTION", final_message)
    if valid and "execution failed" in final_message:
        return False
    if final_message:
        skilled_agent._append_oai_message(final_message, "user", user_proxy)

    reflect_task = """Reflect on the sequence and refactor a into well-documented, generalized python function
    to perform similar tasks for coding steps in future. Make sure the function uses python type hints."""
    user_proxy.initiate_chat(skilled_agent, message=reflect_task, clear_history=False)

    pull_request = skilled_agent.save_to_github()
    await cl.Message(content=f"Saved skill to Github, view Pull Request: {pull_request.html_url}").send()

    return True
