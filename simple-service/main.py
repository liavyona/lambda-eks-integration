# Built-ins
import os
# Third-party
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class LambdaEvent(BaseModel):
    name: str
    age: int


@app.get("/health")
def health():
    return "hello"


@app.post("/hello")
def hello_world(event: LambdaEvent):
    return {
        "message": f"Hello world from {event.name}",
        "event": event
    }


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, port=port, host='0.0.0.0')
