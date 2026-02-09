from google import genai
import inspect

print("Checking google.genai.Client.files.upload signature:")
try:
    # We can't instantiate Client without an API key easily, but we can check the class method if we can find where it is attached.
    # Alternatively, just print help on the module or class structure.
    import google.genai.files
    print(help(genai.Client.files))
except Exception as e:
    print(e)
