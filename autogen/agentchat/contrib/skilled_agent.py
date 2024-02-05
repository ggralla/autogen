import ast
from typing import Dict, List, Optional

import chromadb
from chromadb import Settings
from autogen.agentchat.assistant_agent import ConversableAgent
from autogen.code_utils import content_str, extract_code
from github import Github, GithubException
import uuid


CHROMA_DIR = "./tmp/skilled_agent_db"


class SkilledAgent(ConversableAgent):
    """(Experimental) SkilledAgent, a subclass of ConversableAgent.
    Can learn skills by saving python functions to a vector database
    Can use skills to complete tasks, only retrieving relevant python functionsfrom the vector database."""

    def __init__(
        self,
        name: Optional[str] = "skilledagent",
        system_message: Optional[str] = None,
        memory_config: Optional[Dict] = {},
        github_token: Optional[str] = None,
        **kwargs,
    ):
        if not system_message:
            system_message = """You are a helpful and expert AI assistant.
Solve tasks using your coding and language skills.
Suggest python code to solve the task.
 If a plan is not provided, explain your plan first. Be clear which step uses code, and which step uses your language skill.
When using code, you must indicate the script type in the code block. The user cannot provide any other feedback or perform any other action beyond executing the code you suggest. The user can't modify your code. So do not suggest incomplete code which requires users to modify. Don't use a code block if it's not intended to be executed by the user.
If you want the user to save the code in a file before executing it, put # filename: <filename> inside the code block as the first line. Don't include multiple code blocks in one response. Do not ask users to copy and paste the result. Instead, use 'print' function for the output when relevant. Check the execution result returned by the user.
If the result indicates there is an error, fix the error and output the code again. Suggest the full code instead of partial code or code changes. If the error can't be fixed or if the task is not solved even after the code is executed successfully, analyze the problem, revisit your assumption, collect additional info you need, and think of a different approach to try.
When you find an answer, verify the answer carefully. Include verifiable evidence in your response if possible. Confirm that any code is executed successfully and provides the expected output.
Reply "TERMINATE" in the end when everything is done.
    """
        super().__init__(name=name, system_message=system_message, **kwargs)

        # Valid functions will be tracked here to be saved/remembered later
        self.generated_functions = []

        # Github
        self.github_client = Github(github_token) if github_token else None

        # Assemble the vector db settings.
        self._memory_config = memory_config
        self.verbosity = self._memory_config.get("verbosity", 0)
        self.reset_db = self._memory_config.get("reset_db", False)
        self.recall_threshold = self._memory_config.get("recall_threshold", 1.5)
        self.max_num_retrievals = self._memory_config.get("max_num_retrievals", 10)
        # create the vector db
        self.function_store = FunctionStore(reset=self.reset_db, github_client=self.github_client)
        self.use_skills = False

    # Hook in to generate_reply to save any generated functions
    def generate_reply(self, **kwargs):
        if self.use_skills:
            messages = kwargs["messages"]
            prompt = messages[-1]["content"]
            relevant_functions = self.function_store.get_relevant_functions(
                prompt,
                n_results=self.max_num_retrievals,
                threshold=self.recall_threshold,
            )
            if relevant_functions:
                function_block = ""
                for func_name, func_code in relevant_functions:
                    function_block += (
                        FunctionStore.extract_function_signature(func_code)
                        + "\n"
                        + FunctionStore.extract_docstring(func_code)
                        + "\n"
                    )
                messages += [
                    {
                        "role": "system",
                        "content": f"You may make use of the following Python functions: {function_block}. Assume that the functions are already imported.",
                    }
                ]

        ret = super().generate_reply(**kwargs)
        found_code = extract_code(ret)
        for language, code in found_code:
            if language == "python":
                self.generated_functions.append(code)
        return ret

    def remember_latest_function(self):
        """Remembers the latest function generated by the agent."""
        if self.generated_functions:
            function_code = self.generated_functions[-1]
            function_name = FunctionStore.extract_function_signature(function_code)
            self._remember_function(function_name, function_code)

    def save_to_github(self, github_repo="ggralla/generated_skills", github_branch="main"):
        """Saves the latest function generated by the agent to a github repo."""
        if not self.github_client:
            raise Exception("Github token not provided.")
        if self.generated_functions:
            function_code = self.generated_functions[-1]
            function_name = FunctionStore.extract_function_name(function_code)

            repo = self.github_client.get_repo(github_repo)
            branch = repo.get_branch(github_branch)
            base_branch = repo.get_branch(repo.default_branch)
            try:
                # Create a new branch for the pull request
                new_branch_name = f"add-{function_name}"
                repo.create_git_ref(f"refs/heads/{new_branch_name}", branch.commit.sha)
            except GithubException:
                new_branch_name = f"add-{function_name}-{uuid.uuid4()}"
                repo.create_git_ref(f"refs/heads/{new_branch_name}", branch.commit.sha)

            # Create a new file with the function code
            file_path = f"{function_name}.py"
            commit_message = f"Add {function_name}"
            repo.create_file(file_path, commit_message, function_code, branch=new_branch_name)

            # Create the pull request
            pull_request_title = f"Add {function_name}"
            pull_request_body = f"This pull request adds the function {function_name}.\n {self.messages_to_markdown(list(self.chat_messages.values())[0])}"
            repo.create_pull(
                title=pull_request_title,
                body=pull_request_body,
                base=base_branch.name,
                head=new_branch_name,
            )

    def _remember_function(self, function_name, function_code):
        self.function_store.store_function(function_name, function_code)

    def messages_to_markdown(self, messages: List[Dict]) -> str:
        """Convert a list of messages to markdown format."""
        markdown = ""
        for message in messages:
            # Add role
            markdown += f"**{message['role']}**:\n"
            # Add content
            content = message.get("content")
            markdown += f"{content_str(content)}\n"

        return markdown


class FunctionStore:
    @staticmethod
    def extract_function_name(code):
        module = ast.parse(code)
        for node in module.body:
            if isinstance(node, ast.FunctionDef):
                return node.name
        return None

    @staticmethod
    def extract_function_signature(code):
        module = ast.parse(code)
        for node in module.body:
            if isinstance(node, ast.FunctionDef):
                return f"{node.name}({', '.join(arg.arg for arg in node.args.args)})"
        return None

    @staticmethod
    def extract_docstring(code):
        module = ast.parse(code)
        for node in module.body:
            if isinstance(node, ast.FunctionDef):
                return ast.get_docstring(node)
        return None

    def __init__(self, reset: bool, github_client: Github) -> None:
        settings = Settings(
            anonymized_telemetry=False, allow_reset=True, is_persistent=True, persist_directory=CHROMA_DIR
        )
        self.db_client = chromadb.Client(settings)
        self.vec_db = self.db_client.create_collection("functions", get_or_create=True)  # The collection is the DB.
        self.github_client = github_client

    def store_function(self, function_name, function):
        self.vec_db.add(documents=[function], ids=[function_name])
        print(
            "Function stored in vector database:\n  FUNCTION NAME\n    {}\n  FUNCTION\n    {}".format(
                function_name, function
            )
        )

    def get_relevant_functions(self, query_text, n_results=5, threshold=1.5):
        """Retrieves functions that are related to the given query text within the specified distance threshold."""
        results = self.vec_db.query(query_texts=[query_text], n_results=n_results)
        functions = []
        num_results = len(results["ids"][0])
        for i in range(num_results):
            function_name, function, distance = (
                results["ids"][0][i],
                results["documents"][0][i],
                results["distances"][0][i],
            )
            if distance < threshold:
                print("Function retrieved from vector database: {}".format(function_name))
                """
                print(
                    "\nFUNCTION RETRIEVED FROM VECTOR DATABASE:\n  FUNCTION NAME\n    {}\n  FUNCTION\n    {}\n  DISTANCE\n    {}".format(
                        function_name, function, distance
                    )
                )
                """
                functions.append((function_name, function))
        return functions

    def sync_functions_from_github(self, repo="ggralla/generated_skills", branch="main"):
        """
        Iterates through all files in the repo and adds valid functions to the database
        """
        repo = self.github_client.get_repo(repo)
        contents = repo.get_contents("", ref=branch)
        while contents:
            file_content = contents.pop(0)
            if file_content.type == "dir":
                contents.extend(repo.get_contents(file_content.path))
            elif file_content.type == "file":
                if file_content.name.endswith(".py"):
                    function_name = file_content.name[:-3]
                    function_code = file_content.decoded_content.decode("utf-8")
                    self.store_function(function_name, function_code)