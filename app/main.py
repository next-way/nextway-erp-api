from fastapi import FastAPI

# TODO: Follow https://fastapi.tiangolo.com/tutorial/bigger-applications/

app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Hello World"}
