from google import genai
client = genai.Client()
print(dir(client))
print(hasattr(client, "aio"))
if hasattr(client, "aio"):
    print(dir(client.aio))
