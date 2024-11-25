import os
import re
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from typing_extensions import override
from openai import AssistantEventHandler
from fastapi.middleware.cors import CORSMiddleware
load_dotenv()
error_response = {
                "response": "Oops! It seems something happend wrong to our server... Please try again later.",
                "type": "open_text"
            }
ASSISTANT_ID=os.getenv('ASSISTANT_ID')
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))


class usage(BaseModel):
    prompt_tokens:int
    completion_tokens:int
    total_tokens:int

class ChatInit(BaseModel):
    text:str
    stream:bool=False

class EventHandler(AssistantEventHandler):    
  @override
  def on_text_created(self, text):
    yield text
      
  @override
  def on_text_delta(self, delta, snapshot):
    yield delta.value
      
  def on_tool_call_created(self, tool_call):
    yield tool_call.type
  def on_tool_call_delta(self, delta, snapshot):
    if delta.type == 'code_interpreter':
      if delta.code_interpreter.input:
        yield delta.code_interpreter.input
      if delta.code_interpreter.outputs:
        for output in delta.code_interpreter.outputs:
          if output.type == "logs":
            yield output.logs

    

async def execute_assistant(assistant_id, thread_id, query):
  
    assistant = client.beta.assistants.retrieve(assistant_id=assistant_id)
    thread = client.beta.threads.retrieve(thread_id=thread_id)

    message = client.beta.threads.messages.create(
        thread_id=thread.id, role="user", content=query
    )

    run = client.beta.threads.runs.create_and_poll(
        thread_id=thread.id,
        assistant_id=assistant.id,
        tools= [{"type": "file_search"}]
    )
    
        
    if run.status == 'completed':
        messages = client.beta.threads.messages.list(
            thread_id=thread.id
        )
        print(messages)
        return {
            "message": messages.data[0].content[0].text.value
        } 
    else:
        print(run.status)
        return {
            "message": error_response
        }
        
    


def stream_thread_messages(thread_id):
    with client.beta.threads.runs.stream(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID,
            event_handler=EventHandler(),
        ) as stream:
        try:
            full_message = ""
            for response in stream:
                print(type(response))
                if str(type(response)) == "<class 'openai.types.beta.assistant_stream_event.ThreadMessageDelta'>":
                    message_text = response.data.delta.content[0].text.value
                    full_message += message_text
                    yield message_text
        
        except Exception as e:
            print(f"An error occurred while streaming: {e}")

app = FastAPI()
origins = [
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"]
)

@app.post('/v1/assistant/thread/create')
async def create_thread():
    thread = client.beta.threads.create()
    thread_id = thread.id
    return {
       "thread_id":thread_id
    }

@app.post('/v1/assistant/thread/{thread_id}/chat')
async def chat(
    thread_id:str,
    payload:ChatInit
):
    if thread_id=="new":
        thread = client.beta.threads.create()
        thread_id = thread.id
        print("New thread created with id: ",thread_id)
    

    try:
        if not payload.stream:
            response = await execute_assistant(
                assistant_id=ASSISTANT_ID, 
                thread_id=thread_id, 
                query=payload.text
            )
         
            return {
                "success":True,
                "thread_id":thread_id,
                "message":re.sub(r'【[^【】]*】', '', response["message"])
            }
        else:
            message = client.beta.threads.messages.create(
                thread_id=thread_id, role="user", content=payload.text
            )
            return StreamingResponse(stream_thread_messages(thread_id), media_type="text/event-stream")
    
    except Exception as e:
        print(str(e))
        return {
                "success":True,
                "thread_id":thread_id,
                "message":error_response
            }

