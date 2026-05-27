import litellm
litellm.set_verbose = True
litellm._turn_on_debug()

from pandasai_litellm.litellm import LiteLLM
import os

os.environ["GEMINI_API_KEY"] = "AIzaSyB18RhBigW10p_qSLhVvkndkyMRwRyKYAI"

try:
    llm = LiteLLM(model='gemini/gemini-1.5-flash')
    response = llm.call(instruction='Respond YES')
    print("RESPONSE:", response)
except Exception as e:
    print("ERROR:", e)
