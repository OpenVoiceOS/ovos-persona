import json
import os
from os.path import dirname

from ovos_plugin_manager.solvers import find_question_solver_plugins
from ovos_utils.log import LOG

from ovos_persona.solvers import QuestionSolversService


class Persona:
    def __init__(self, name, config, blacklist=None):
        blacklist = blacklist or []
        self.name = name
        self.config = config
        persona = config.get("solvers") or ["ovos-solver-failure-plugin"]
        plugs = {}
        for plug_name, plug in find_question_solver_plugins().items():
            if plug_name not in persona or plug_name in blacklist:
                plugs[plug_name] = {"enabled": False}
            else:
                plugs[plug_name] = config.get(plug_name) or {"enabled": True}
        self.solvers = QuestionSolversService(config=plugs)

    def complete(self, prompt: str, context: dict = None):
        return self.solvers.spoken_answer(prompt, context)

    def chat(self, messages: list = None, context: dict = None):
        # TODO - message history solver
        #messages = [
        #    {"role": "system", "content": "You are a helpful assistant."},
        #    {"role": "user", "content": "Knock knock."},
        #    {"role": "assistant", "content": "Who's there?"},
        #    {"role": "user", "content": "Orange."},
        #]
        prompt = messages[-1]["content"]
        return self.solvers.spoken_answer(prompt, context)


class PersonaService:
    def __init__(self, personas_path, persona_blacklist=None):
        self.personas = {}
        self.blacklist = persona_blacklist or []
        self.load_personas(personas_path)

    def load_personas(self, personas_path):
        # load personas provided by packages
        try:
            from ovos_plugin_manager.persona import find_persona_plugins
            for name, persona in find_persona_plugins().items():
                if name in self.blacklist:
                    continue
                self.personas[name] = Persona(name, persona)
        except ImportError:
            LOG.error("update ovos-plugin-manager for persona plugin support")

        # load user defined personas
        os.makedirs(personas_path, exist_ok=True)
        for p in os.listdir(personas_path):
            if not p.endswith(".json"):
                continue
            name = p.replace(".json", "")
            if name in self.blacklist:
                continue
            with open(f"{personas_path}/{p}") as f:
                persona = json.load(f)
            self.personas[name] = Persona(name, persona)

    def register_persona(self, name, persona):
        self.personas[name] = Persona(name, persona)

    def deregister_persona(self, name):
        if name in self.personas:
            self.personas.pop(name)

    # Chatbot API
    def chatbox_ask(self, prompt, persona="eliza", lang=None):
        context = {"lang": lang} if lang else {}
        if persona not in self.personas:
            raise ValueError(f"unknown persona, choose one of {self.personas.keys()}")
        return self.personas[persona].complete(prompt, context)


if __name__ == "__main__":
    b = PersonaService(f"{dirname(dirname(__file__))}/personas",
                       persona_blacklist=["omniscient oracle"])


    def test_persona(persona="eliza"):
        print(b.chatbox_ask("what is the speed of light", persona))
        print(b.chatbox_ask("who invented the telephone", persona))
        print(b.chatbox_ask("who is stephen hawking", persona))
        print(b.chatbox_ask("what is the meaning of life?", persona))
        print(b.chatbox_ask("what is your favorite animal?", persona))


    test_persona("eliza")
    # What answer would please you most?
    # What comes to mind when you ask that?
    # What comes to mind when you ask that?
    # What answer would please you most?
    # Why do you ask?

    test_persona("webdude")
    # The speed of light has a value of about 300 million meters per second
    # The telephone was invented by Alexander Graham Bell
    # Stephen William Hawking (8 January 1942 – 14 March 2018) was an English theoretical physicist, cosmologist, and author who, at the time of his death, was director of research at the Centre for Theoretical Cosmology at the University of Cambridge.
    # 42
    # critical error, brain not available
