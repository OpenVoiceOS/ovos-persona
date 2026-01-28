from typing import Dict, List, Optional, Any

from ovos_plugin_manager.templates.agents import MessageRole, AgentMessage, AgentContextManager


class BasicShortTermMemory(AgentContextManager):
    """
    Minimal in-memory implementation of AgentContextManager.

    Stores session histories in memory with optional truncation based on max_history.

    Args:
        config (dict): Configuration options, supports:
            - max_history (int): Maximum number of messages to retain per session.
            - system_prompt (str): Base system prompt to prepend to context.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.session2history: Dict[str, List[AgentMessage]] = {}

    def get_history(self, session_id: str) -> List[AgentMessage]:
        """
        Retrieve the current session's message history.

        Returns a copy to prevent external mutation.

        Args:
            session_id (str): Identifier for the conversation session.

        Returns:
            List[AgentMessage]: The message history for the session.
        """
        return list(self.session2history.get(session_id, []))

    def update_history(self, new_messages: List[AgentMessage], session_id: str):
        """
        Update the session history by appending new messages.

        Truncates history if it exceeds max_history in config.

        Args:
            new_messages (List[AgentMessage]): New messages to append.
            session_id (str): Identifier for the conversation session.
        """
        if session_id not in self.session2history:
            self.session2history[session_id] = []
        else:
            last_message = self.session2history[session_id][-1]
            next_message = new_messages[0]

            # drop any hanging user messages without a corresponding response
            if next_message.role == MessageRole.USER and last_message.role == MessageRole.USER:
                self.session2history[session_id].pop()
            # merge consecutive speak messages
            if next_message.role == MessageRole.ASSISTANT and last_message.role == MessageRole.ASSISTANT:
                new_messages[0].content = last_message.content + "\n" + next_message.content
                self.session2history[session_id].pop()

        self.session2history[session_id] += new_messages
        max_size = self.config.get("max_history", 5)
        if len(self.session2history[session_id]) > max_size:
            self.session2history[session_id] = self.session2history[session_id][-max_size:]

    def build_conversation_context(self, utterance: str, session_id: str) -> List[AgentMessage]:
        """
        Produce augmented context for the agent by combining system prompt,
        session history, and current user input.

        Args:
            utterance (str): The latest user input.
            session_id (str): Identifier for the conversation session.

        Returns:
            List[AgentMessage]: Messages representing the augmented context.
        """
        message_history = self.get_history(session_id)
        if message_history:
            # drop any hanging user messages without a corresponding response
            # for any non-verbal actions that OVOS may take
            while message_history[-1].role == MessageRole.USER:
                message_history.pop()

        if self.system_prompt.strip():
            message_history.insert(0, AgentMessage(role=MessageRole.SYSTEM, content=self.system_prompt.strip()))
        message_history.append(AgentMessage(role=MessageRole.USER, content=utterance.strip()))
        return message_history
